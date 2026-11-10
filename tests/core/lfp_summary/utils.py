from pathlib import Path

import h5py
import numpy as np

from app.core.lfp_summary.ranges import ReadRange
from app.core.lfp_summary.summary import undo_residuals, unzigzag


def write_report(
    path: Path,
    *,
    cells: int = 3,
    contacts: int = 4,
    steps: int = 50,
    populations: tuple[str, ...] = ("pop",),
    chunked: bool = False,
    units: str = "V",
    seed: int = 0,
) -> np.ndarray:
    """A per-cell SONATA LFP report, every cell on every contact. Returns its total in uV."""
    rng = np.random.default_rng(seed)
    total = np.zeros((steps, contacts))
    scale = {"V": 1e6, "mV": 1e3, "uV": 1.0}[units]
    with h5py.File(path, "w") as f:
        for i, name in enumerate(populations):
            data = rng.normal(0, 1e-5, (steps, cells * contacts)).astype(np.float32)
            g = f.create_group(f"report/{name}")
            g.create_dataset("data", data=data, chunks=(8, contacts) if chunked else None)
            g["data"].attrs["units"] = units
            g["mapping/node_ids"] = np.arange(i * cells, (i + 1) * cells, dtype=np.uint64)
            g["mapping/index_pointers"] = np.arange(0, (cells + 1) * contacts, contacts)
            g["mapping/element_ids"] = np.tile(np.arange(contacts, dtype=np.uint32), cells)
            g["mapping/time"] = np.array([0.0, steps * 0.1, 0.1])
            total += data.reshape(steps, cells, contacts).sum(1, dtype=np.float64) * scale
    return total


def decoded(h5: h5py.File, level: dict, group: int, contact: int) -> np.ndarray:
    """A group's contact's row of the index's level, as h5py reads it, decoded: block by block,
    unzigzagged and its residuals added back up by its order, along the flat block.
    """
    codes = h5[level["dataset"]][group, contact]
    orders = h5[level["blocks"]["predictors"]][group, contact]
    steps = level["blocks"]["steps"]
    blocks = [
        undo_residuals(unzigzag(codes[b * steps : (b + 1) * steps]), int(order))
        for b, order in enumerate(orders)
    ]
    return np.concatenate(blocks).reshape(codes.shape)


def local_reader(path: Path) -> tuple[ReadRange, int]:
    content = path.read_bytes()

    def read(offset: int, length: int) -> bytes:
        return content[offset : offset + length]

    return read, len(content)


def write_nodes(path: Path, population: str, columns: dict[str, list]) -> None:
    """A SONATA nodes file: text columns as indices into their library, others as they are."""
    with h5py.File(path, "w") as f:
        group = f.create_group(f"nodes/{population}/0")
        for name, values in columns.items():
            if isinstance(values[0], str):
                library = sorted(set(values))
                group.create_dataset(f"@library/{name}", data=library, dtype=h5py.string_dtype())
                group[name] = np.array([library.index(v) for v in values], np.uint32)
            else:
                group[name] = np.array(values)
