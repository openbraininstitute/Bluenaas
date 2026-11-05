"""The groups a circuit's cells fall in, from its SONATA nodes file, read by range."""

import h5py
import numpy as np

from app.core.lfp_summary.ranges import RangeFile, ReadRange

# The columns a report's field is split by, in the order of the summary's index
GROUP_COLUMNS = ["mtype", "etype", "synapse_class", "layer", "region"]


def _text(values: np.ndarray) -> np.ndarray:
    if values.dtype.kind == "O":
        return np.array([v.decode() if isinstance(v, bytes) else str(v) for v in values])
    return values.astype(str)


def cell_labels(
    read: ReadRange, size: int, population: str, node_ids: np.ndarray
) -> dict[str, np.ndarray]:
    """The label of each of the population's cells given, per column of GROUP_COLUMNS it has."""
    with h5py.File(RangeFile(read, size), "r") as f:
        columns = f.get(f"nodes/{population}/0")
        if not isinstance(columns, h5py.Group):
            return {}
        labels = {}
        for name in GROUP_COLUMNS:
            column = columns.get(name)
            if not isinstance(column, h5py.Dataset):
                continue
            # Text columns are usually indices into their library
            library = columns.get(f"@library/{name}")
            values = column[:][node_ids]
            labels[name] = (
                _text(library[:])[values] if isinstance(library, h5py.Dataset) else _text(values)
            )
        return labels
