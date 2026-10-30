"""The summary of a SONATA LFP report, per-cell or summed, in the format the web app's viewer reads.

The summary is one HDF5 file whose datasets are all contiguous and uncompressed, plus a JSON index
of their byte offsets, so a browser reads any slice with an HTTP Range request and no HDF5 library.
Python users open the h5 as usual.

Layout, per axis (the total is the axis "total" with one group):
  /lfp/{axis}/level0     int16  group x contact x step, value = raw * scale[group] uV
  /lfp/{axis}/level{k}   int16  group x contact x bin x 2 (min, max over 2**k steps),
                                only while steps > MAX_OVERVIEW_STEPS, halving until under
  /lfp/{axis}/stats      float32 group x contact x len(STATS)
  /lfp/{axis}/psd        float32 group x contact x frequency, Welch, uV^2/Hz
  /lfp/correlation       int16  contact x contact, value = raw / 32767, total only
  /report/{pop}/...      the float32 total in V, laid out as sonata-extension#51
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from app.core.lfp_summary.ranges import RangeFile, ReadRange
from app.domains.simulation_result.lfp_summary import NoSummaryReason

MAX_OVERVIEW_STEPS = 2048
STATS = ["min", "max", "ptp", "rms", "mean", "trough_ms"]
WELCH_SEGMENT = 256

# The report is read in blocks of rows of about this size, this many at once
BLOCK_BYTES = 32 << 20
READS_IN_FLIGHT = 8

# The total is summed in memory, steps x contacts in float64, and the summary built from it
MAX_TOTAL_BYTES = 2 << 30

TO_UV = {"V": 1e6, "mV": 1e3, "uV": 1.0, "µV": 1.0}


class NotSummarisableError(Exception):
    def __init__(self, reason: NoSummaryReason, details: str):
        super().__init__(details)
        self.reason = reason


@dataclass
class SummedReport:
    populations: list[str]
    start: float
    dt: float
    # steps x contacts, uV
    total: np.ndarray


@dataclass
class _Population:
    data: h5py.Dataset
    element_ids: np.ndarray
    cells: int
    to_uv: float


def _not_a_report(details: str) -> NotSummarisableError:
    return NotSummarisableError(NoSummaryReason.NOT_LFP_REPORT, details)


def _group(parent: h5py.Group, path: str) -> h5py.Group:
    node = parent.get(path)
    if not isinstance(node, h5py.Group):
        raise _not_a_report(f"No group {parent.name}/{path}")
    return node


def _dataset(parent: h5py.Group, path: str) -> h5py.Dataset:
    node = parent.get(path)
    if not isinstance(node, h5py.Dataset):
        raise _not_a_report(f"No dataset {parent.name}/{path}")
    return node


def _population(group: h5py.Group) -> _Population:
    data = _dataset(group, "data")
    units = data.attrs.get("units", "V")
    units = units.decode() if isinstance(units, bytes) else str(units)
    if units not in TO_UV:
        raise NotSummarisableError(NoSummaryReason.UNREADABLE, f"Unknown units {units}")
    element_ids = np.asarray(_dataset(group, "mapping/element_ids")[:])
    if data.ndim != 2 or not len(element_ids):
        raise _not_a_report(f"{group.name} has no data on any contact")
    return _Population(
        data=data,
        element_ids=element_ids,
        cells=len(_dataset(group, "mapping/node_ids")),
        to_uv=TO_UV[units],
    )


def _sum_population(
    population: _Population, read: ReadRange, total: np.ndarray, *, workers: int
) -> None:
    data, eids, cells = population.data, population.element_ids, population.cells
    steps, contacts = total.shape
    regular = len(eids) == cells * contacts and bool(
        (eids.reshape(cells, contacts) == np.arange(contacts)).all()
    )

    offset = data.id.get_offset()
    # Read by range where the rows lie one after the other in the file, else through h5py
    contiguous = offset is not None and data.chunks is None
    row_bytes = data.shape[1] * data.dtype.itemsize
    rows_per_block = max(1, BLOCK_BYTES // row_bytes)

    def summed(a: int) -> tuple[int, np.ndarray]:
        b = min(steps, a + rows_per_block)
        if offset is not None and contiguous:
            raw = read(offset + a * row_bytes, (b - a) * row_bytes)
            rows = np.frombuffer(raw, data.dtype).reshape(b - a, data.shape[1])
        else:
            rows = np.asarray(data[a:b])
        if regular:
            return a, rows.reshape(b - a, cells, contacts).sum(1, dtype=np.float64)
        return a, np.stack([np.bincount(eids, weights=row, minlength=contacts) for row in rows])

    with ThreadPoolExecutor(workers if contiguous else 1) as pool:
        for a, values in pool.map(summed, range(0, steps, rows_per_block)):
            total[a : a + len(values)] += values * population.to_uv


def sum_report(read: ReadRange, size: int, *, workers: int = READS_IN_FLIGHT) -> SummedReport:
    """The report's total over its cells, read by range."""
    try:
        f = h5py.File(RangeFile(read, size), "r")
    except OSError as ex:
        raise NotSummarisableError(NoSummaryReason.NOT_LFP_REPORT, f"Not an HDF5 file: {ex}")

    with f:
        report = _group(f, "report")
        names = list(report)
        if not names:
            raise _not_a_report("No population in /report")
        populations = [_population(_group(report, name)) for name in names]
        times = np.asarray(_dataset(_group(report, names[0]), "mapping/time")[:])
        steps = populations[0].data.shape[0]
        contacts = 1 + max(int(p.element_ids.max()) for p in populations)

        if any(p.data.shape[0] != steps for p in populations):
            raise NotSummarisableError(
                NoSummaryReason.UNREADABLE, "The populations have different numbers of steps"
            )
        if steps * contacts * 8 > MAX_TOTAL_BYTES:
            raise NotSummarisableError(
                NoSummaryReason.TOO_LARGE, f"{steps} steps x {contacts} contacts"
            )

        total = np.zeros((steps, contacts), np.float64)
        for population in populations:
            _sum_population(population, read, total, workers=workers)

    return SummedReport(populations=names, start=float(times[0]), dt=float(times[2]), total=total)


def quantize(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """int16 with one scale per group: steps x groups x contacts -> group x contact x step."""
    peak = np.abs(values).max(axis=(0, 2))
    scales = np.where(peak > 0, peak / 32767, 1.0)
    q = np.round(values / scales[None, :, None]).astype(np.int16)
    return np.ascontiguousarray(q.transpose(1, 2, 0)), scales


def min_max_levels(level0: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Min/max of each 2**k steps, halving until the bins are under MAX_OVERVIEW_STEPS."""
    levels = []
    lo, hi = level0, level0
    k = 0
    while lo.shape[-1] > MAX_OVERVIEW_STEPS:
        k += 1
        n = lo.shape[-1] // 2 * 2
        rest = lo.shape[-1] - n
        lo2 = np.minimum(lo[..., 0:n:2], lo[..., 1:n:2])
        hi2 = np.maximum(hi[..., 0:n:2], hi[..., 1:n:2])
        if rest:
            lo2 = np.concatenate([lo2, lo[..., n:]], axis=-1)
            hi2 = np.concatenate([hi2, hi[..., n:]], axis=-1)
        lo, hi = lo2, hi2
        levels.append((k, np.ascontiguousarray(np.stack([lo, hi], axis=-1))))
    return levels


def contact_stats(values: np.ndarray, start: float, dt: float) -> np.ndarray:
    """Per group and contact: STATS, from steps x groups x contacts."""
    trough = start + values.argmin(axis=0) * dt
    return np.stack(
        [
            values.min(axis=0),
            values.max(axis=0),
            np.ptp(values, axis=0),
            np.sqrt((values**2).mean(axis=0)),
            values.mean(axis=0),
            trough,
        ],
        axis=-1,
    ).astype(np.float32)


def welch(values: np.ndarray, dt_ms: float) -> tuple[np.ndarray, np.ndarray]:
    """One-sided Welch density in uV^2/Hz, Hann window, half overlap, mean removed per segment."""
    steps = values.shape[0]
    # A quarter of the run, as a power of two: segments to average over, at a resolution that
    # holds below the gamma band whatever dt is.
    n = min(steps, max(WELCH_SEGMENT, 2 ** int(np.floor(np.log2(max(1, steps / 4))))))
    hop = max(1, n // 2)
    window = np.hanning(n)
    fs = 1000.0 / dt_ms
    norm = fs * (window**2).sum()
    psd = np.zeros((n // 2 + 1,) + values.shape[1:], np.float64)
    segments = 0
    for a in range(0, steps - n + 1, hop):
        seg = values[a : a + n]
        seg = seg - seg.mean(axis=0)
        spec = np.fft.rfft(seg * window.reshape((n,) + (1,) * (values.ndim - 1)), axis=0)
        psd += np.abs(spec) ** 2
        segments += 1
    if norm > 0:
        psd /= segments * norm
    if n % 2 == 0:
        psd[1:-1] *= 2
    else:
        psd[1:] *= 2
    freqs = np.fft.rfftfreq(n, d=dt_ms / 1000.0)
    return np.ascontiguousarray(np.moveaxis(psd, 0, -1)).astype(np.float32), freqs


def correlation(total: np.ndarray) -> np.ndarray:
    """Zero-lag Pearson correlation between contacts, as int16 / 32767."""
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.atleast_2d(np.corrcoef(total.T))
    return np.round(np.nan_to_num(c) * 32767).astype(np.int16)


def write_summary(report: SummedReport, h5_path: Path, *, version: int, source: dict) -> dict:
    """Write the summary's h5 at `h5_path`. Returns its index."""
    start, dt = report.start, report.dt
    steps, contacts = report.total.shape
    fields = {"total": (["total"], report.total[:, None, :])}
    axes = []
    written = {}
    freqs = np.zeros(0)
    with h5py.File(h5_path, "w", libver="latest") as h5:
        for axis, (groups, values) in fields.items():
            level0, scales = quantize(values)
            written[f"/lfp/{axis}/level0"] = h5.create_dataset(f"lfp/{axis}/level0", data=level0)
            levels = min_max_levels(level0)
            for k, level in levels:
                written[f"/lfp/{axis}/level{k}"] = h5.create_dataset(
                    f"lfp/{axis}/level{k}", data=level
                )
            written[f"/lfp/{axis}/stats"] = h5.create_dataset(
                f"lfp/{axis}/stats", data=np.ascontiguousarray(contact_stats(values, start, dt))
            )
            psd, freqs = welch(values, dt)
            written[f"/lfp/{axis}/psd"] = h5.create_dataset(f"lfp/{axis}/psd", data=psd)
            axes.append(
                {
                    "name": axis,
                    "groups": list(groups),
                    "scales": [float(s) for s in scales],
                    "levels": [
                        {"step": 1, "kind": "value", "dataset": f"/lfp/{axis}/level0"},
                        *(
                            {"step": 2**k, "kind": "min_max", "dataset": f"/lfp/{axis}/level{k}"}
                            for k, _ in levels
                        ),
                    ],
                    "stats": f"/lfp/{axis}/stats",
                    "psd": f"/lfp/{axis}/psd",
                }
            )
        written["/lfp/correlation"] = h5.create_dataset(
            "lfp/correlation", data=correlation(report.total)
        )
        # The total as sonata-extension#51 has it, for libsonata and bluepysnap
        g = h5.create_group(f"report/{'+'.join(report.populations)}")
        g.create_dataset("data", data=(report.total / 1e6).astype(np.float32)).attrs["units"] = "V"
        m = g.create_group("mapping")
        m["node_ids"] = np.array([0], np.uint64)
        m["index_pointers"] = np.array([0, contacts], np.uint64)
        m["element_ids"] = np.arange(contacts, dtype=np.uint32)
        m["time"] = np.array([start, start + steps * dt, dt])
        h5.flush()
        datasets = {
            name: {
                "offset": int(d.id.get_offset()),
                "shape": list(d.shape),
                "dtype": d.dtype.str,
            }
            for name, d in written.items()
        }

    return {
        "format": "lfp-summary",
        "version": version,
        "source": source,
        "populations": report.populations,
        "time": {"start": start, "dt": dt, "steps": steps},
        "units": "uV",
        "contacts": contacts,
        "stats": STATS,
        "psd_frequencies": [float(f) for f in freqs],
        "axes": axes,
        "correlation": {"dataset": "/lfp/correlation", "scale": 1 / 32767},
        "datasets": datasets,
    }


def verify(h5_path: Path, index: dict) -> None:
    """Every dataset read as raw bytes at its offset equals the dataset."""
    raw = np.memmap(h5_path, dtype=np.uint8, mode="r")
    with h5py.File(h5_path, "r") as h5:
        for name, d in index["datasets"].items():
            dtype = np.dtype(d["dtype"])
            n = int(np.prod(d["shape"])) * dtype.itemsize
            view = raw[d["offset"] : d["offset"] + n].view(dtype).reshape(d["shape"])
            if not np.array_equal(view, _dataset(h5, name)[:]):
                raise AssertionError(f"{name} is not where the index says it is")
