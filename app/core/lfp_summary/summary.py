"""The summary of a SONATA LFP report, per-cell or summed, in the format the web app's viewer reads.

The summary is one HDF5 file plus a JSON index of its datasets' byte offsets, so a browser reads any
slice with an HTTP Range request and no HDF5 library. It is made for the browser alone.

The total, the axis "total" with one group:
  /lfp/total/level0      int16  group x contact x step, value = raw * scale[group] uV
  /lfp/total/level{k}    int16  group x contact x bin x 2 (min, max over 2**k steps),
                                only while steps > MAX_OVERVIEW_STEPS, halving until under
  /lfp/total/stats       float32 group x contact x len(STATS)
  /lfp/total/psd         float32 group x contact x frequency, Welch, uV^2/Hz
  /lfp/correlation       int16  contact x contact, value = raw / 32767

The field of each group of cells, on each axis of GROUP_COLUMNS the report's cells differ on:
  /lfp/{axis}/level0     int16  group x contact x step, as the total's. Past MAX_OVERVIEW_STEPS it
                                is in chunks of one contact's row, shuffled and deflated, not listed
                                in the index's datasets, and these two are added:
  /lfp/{axis}/chunks     uint64 group x contact x 2, each chunk's byte offset and size in the file
  /lfp/{axis}/level{k}   int16  group x contact x bin, the mean over 2**k steps at the k the total
                                ends on: means of groups add up, as min and max don't
  /lfp/{axis}/stats      float32 group x contact x len(STATS)
  /lfp/{axis}/psd        float32 group x contact x frequency, the Welch means over PSD_BANDS bands
"""

import math
import time
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import h5py
import numpy as np
from loguru import logger

from app.core.lfp_summary.nodes import GROUP_COLUMNS
from app.core.lfp_summary.ranges import RangeFile, ReadRange
from app.domains.simulation_result.lfp_summary import NoSummaryReason

MAX_OVERVIEW_STEPS = 2048
STATS = ["min", "max", "ptp", "rms", "mean", "trough_ms"]
WELCH_SEGMENT = 256
# Else the index's frequencies and the spectra grow with the run
WELCH_MAX_SEGMENT = 1 << 16
PSD_BANDS = 128

DEFLATE_LEVEL = 6
DEFLATES_AT_ONCE = 4

# The report is read in blocks of rows of about this size, this many at once
BLOCK_BYTES = 32 << 20
READS_IN_FLIGHT = 8

# How often the read of a report says how far it has got, at most
PROGRESS_LOG_SECONDS = 30.0

# The total is summed in memory, steps x contacts in float64, and the summary built from it
MAX_TOTAL_BYTES = 2 << 30
# Summing and writing peak at about 3.3 times the total (measured), besides the reads in flight
PEAK_PER_TOTAL_BYTE = 3.5
FIXED_PEAK_BYTES = 1 << 30
# Each group's field is held in memory too, as float32
GROUP_FIELD_SAMPLE_BYTES = 4

TO_UV = {"V": 1e6, "mV": 1e3, "uV": 1.0, "µV": 1.0}

# A population's cells, by their node ids: their labels per column of GROUP_COLUMNS it has
CellLabels = Callable[[str, np.ndarray], dict[str, np.ndarray]]


def duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.0f} min"


class ReadProgress:
    """Logs how far the read of a report has got: only numbers and its label, never its URL."""

    def __init__(self, label: str, total_bytes: int):
        self.label = label
        self.total_bytes = total_bytes
        self.done = 0
        self.started = self.logged_at = time.monotonic()
        self.logged_bytes = 0

    def add(self, count: int) -> None:
        self.done += count
        now = time.monotonic()
        if now - self.logged_at < PROGRESS_LOG_SECONDS:
            return
        recent = (self.done - self.logged_bytes) / (now - self.logged_at)
        average = self.done / (now - self.started)
        left = (self.total_bytes - self.done) / recent if recent else 0
        logger.info(
            f"LFP report {self.label}: read {self.done / 1e9:.1f} of {self.total_bytes / 1e9:.1f} GB"
            f" ({100 * self.done / self.total_bytes:.0f}%), {recent / 1e6:.0f} MB/s,"
            f" {average / 1e6:.0f} MB/s on average, about {duration(left)} left"
        )
        self.logged_at = now
        self.logged_bytes = self.done

    def finish(self) -> None:
        seconds = time.monotonic() - self.started
        speed = self.done / seconds if seconds else 0
        logger.info(
            f"LFP report {self.label}: read {self.done / 1e9:.1f} GB in {duration(seconds)},"
            f" {speed / 1e6:.0f} MB/s on average"
        )


class NotSummarisableError(Exception):
    def __init__(self, reason: NoSummaryReason, details: str):
        super().__init__(details)
        self.reason = reason


class OverMemoryError(Exception):
    """The summary would take more memory than the build has."""


@dataclass
class GroupFields:
    groups: list[str]
    # steps x groups x contacts, uV
    values: np.ndarray


@dataclass
class SummedReport:
    populations: list[str]
    start: float
    dt: float
    # steps x contacts, uV
    total: np.ndarray
    # By axis, none where the report's cells can't be told apart
    fields: dict[str, GroupFields]


@dataclass
class _Population:
    name: str
    data: h5py.Dataset
    element_ids: np.ndarray
    node_ids: np.ndarray
    to_uv: float

    @property
    def cells(self) -> int:
        return len(self.node_ids)

    def is_regular(self, contacts: int) -> bool:
        """Every cell on every contact, in order."""
        return len(self.element_ids) == self.cells * contacts and bool(
            (self.element_ids.reshape(self.cells, contacts) == np.arange(contacts)).all()
        )


@dataclass
class _CellOrder:
    """How to add up a population's cells into groups: the cells in the order of their group, where
    each group starts, and which of the axis's groups each is.
    """

    permutation: np.ndarray
    starts: np.ndarray
    groups: np.ndarray


def _not_a_report(details: str) -> NotSummarisableError:
    return NotSummarisableError(NoSummaryReason.NOT_LFP_REPORT, details)


def _unreadable(details: str) -> NotSummarisableError:
    return NotSummarisableError(NoSummaryReason.UNREADABLE, details)


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
    units = data.attrs.get("units")
    if units is None:
        raise _unreadable(f"{group.name} has no units")
    units = units.decode() if isinstance(units, bytes) else str(units)
    if units not in TO_UV:
        raise _unreadable(f"Unknown units {units}")
    element_ids = np.asarray(_dataset(group, "mapping/element_ids")[:])
    if data.ndim != 2 or not len(element_ids):
        raise _not_a_report(f"{group.name} has no data on any contact")
    if data.shape[1] != len(element_ids):
        raise _unreadable(
            f"{group.name} has {data.shape[1]} columns and {len(element_ids)} element ids"
        )
    if not np.issubdtype(element_ids.dtype, np.integer) or element_ids.min() < 0:
        raise _unreadable(f"The element ids of {group.name} are not contacts")
    return _Population(
        name=str(PurePosixPath(group.name).name),
        data=data,
        element_ids=element_ids,
        node_ids=np.asarray(_dataset(group, "mapping/node_ids")[:]),
        to_uv=TO_UV[units],
    )


def _cell_orders(
    populations: list[_Population], contacts: int, labels_of: CellLabels
) -> tuple[dict[str, list[str]], dict[str, dict[str, _CellOrder]]]:
    """The groups of each axis the cells differ on, and the order of each population's cells for
    it. Only an axis every population has: its groups must add up to the total. None where the cells
    are not all on all contacts, which is no report that is written, and saves a slower sum.
    """
    groups = {}
    orders: dict[str, dict[str, _CellOrder]] = {p.name: {} for p in populations}
    if not all(p.is_regular(contacts) for p in populations):
        return groups, orders
    labels = {p.name: labels_of(p.name, p.node_ids) for p in populations}
    for axis in GROUP_COLUMNS:
        if not all(axis in labels[p.name] for p in populations):
            continue
        names = np.unique(np.concatenate([labels[p.name][axis] for p in populations]))
        if len(names) < 2:
            continue
        groups[axis] = [str(name) for name in names]
        for p in populations:
            which = np.searchsorted(names, labels[p.name][axis])
            permutation = np.argsort(which, kind="stable")
            starts = np.flatnonzero(np.r_[True, np.diff(which[permutation]) != 0])
            orders[p.name][axis] = _CellOrder(permutation, starts, which[permutation][starts])
    return groups, orders


def _sum_population(
    population: _Population,
    read: ReadRange,
    total: np.ndarray,
    fields: dict[str, GroupFields],
    orders: dict[str, _CellOrder],
    progress: ReadProgress,
    *,
    workers: int,
) -> None:
    data, eids, cells = population.data, population.element_ids, population.cells
    steps, contacts = total.shape
    regular = population.is_regular(contacts)

    offset = data.id.get_offset()
    # Read by range where the rows lie one after the other in the file, else through h5py
    contiguous = offset is not None and data.chunks is None
    row_bytes = data.shape[1] * data.dtype.itemsize
    rows_per_block = max(1, BLOCK_BYTES // row_bytes)

    def summed(a: int) -> tuple[int, np.ndarray, dict[str, np.ndarray]]:
        b = min(steps, a + rows_per_block)
        if offset is not None and contiguous:
            raw = read(offset + a * row_bytes, (b - a) * row_bytes)
            rows = np.frombuffer(raw, data.dtype).reshape(b - a, data.shape[1])
        else:
            rows = np.asarray(data[a:b])
        if not regular:
            rows_total = np.stack(
                [np.bincount(eids, weights=row, minlength=contacts) for row in rows]
            )
            return a, rows_total, {}
        cube = rows.reshape(b - a, cells, contacts)
        grouped = {
            axis: np.add.reduceat(
                cube[:, order.permutation], order.starts, axis=1, dtype=np.float64
            )
            for axis, order in orders.items()
        }
        return a, cube.sum(1, dtype=np.float64), grouped

    with ThreadPoolExecutor(workers if contiguous else 1) as pool:
        for a, values, grouped in pool.map(summed, range(0, steps, rows_per_block)):
            b = a + len(values)
            total[a:b] += values * population.to_uv
            for axis, by_group in grouped.items():
                fields[axis].values[a:b, orders[axis].groups] += by_group * population.to_uv
            progress.add((b - a) * row_bytes)


def peak_bytes(steps: int, contacts: int, group_fields: int = 0) -> int:
    """The memory a summary of this many steps, contacts and fields of groups takes, at most."""
    per_sample = 8 * PEAK_PER_TOTAL_BYTE + group_fields * GROUP_FIELD_SAMPLE_BYTES
    return int(steps * contacts * per_sample) + FIXED_PEAK_BYTES


def _no_labels(_population: str, _node_ids: np.ndarray) -> dict[str, np.ndarray]:
    return {}


def _axes_in_memory(
    groups: dict[str, list[str]], steps: int, contacts: int, memory: int
) -> dict[str, list[str]]:
    """The axes that fit: the largest are left out first, as they cost the most."""
    kept = dict(groups)
    while peak_bytes(steps, contacts, sum(len(g) for g in kept.values())) > memory:
        largest = max(kept, key=lambda axis: len(kept[axis]))
        logger.warning(f"The fields by {largest} of an LFP report would not fit in the memory")
        del kept[largest]
    return kept


def sum_report(
    read: ReadRange,
    size: int,
    *,
    labels_of: CellLabels = _no_labels,
    label: str = "",
    memory: int | None = None,
    move_for_groups: bool = False,
    workers: int = READS_IN_FLIGHT,
) -> SummedReport:
    """The report's total over its cells and its fields per group of cells, read by range.

    Raises `OverMemoryError` before they are allocated where the summary would take more than
    `memory`. Where only the groups take it over, it is raised if `move_for_groups`, for a build
    that can move to a larger queue, and otherwise the fields that don't fit are left out: a report
    is better summarised without them than not at all.
    """
    try:
        f = h5py.File(RangeFile(read, size), "r")
    except OSError as ex:
        raise _not_a_report(f"Not an HDF5 file: {ex}")

    with f:
        report = _group(f, "report")
        names = list(report)
        if not names:
            raise _not_a_report("No population in /report")
        populations = [_population(_group(report, name)) for name in names]
        times = np.asarray(_dataset(_group(report, names[0]), "mapping/time")[:])
        steps = populations[0].data.shape[0]
        contacts = 1 + max(int(p.element_ids.max()) for p in populations)

        if times.shape != (3,) or not times[2] > 0:
            raise _unreadable("The mapping's time is not start, end and step")
        if not steps:
            raise _unreadable("The report has no steps")
        if any(p.data.shape[0] != steps for p in populations):
            raise _unreadable("The populations have different numbers of steps")
        if steps * contacts * 8 > MAX_TOTAL_BYTES:
            raise NotSummarisableError(
                NoSummaryReason.TOO_LARGE, f"{steps} steps x {contacts} contacts"
            )
        if memory is not None and peak_bytes(steps, contacts) > memory:
            raise OverMemoryError(
                f"{steps} steps x {contacts} contacts take over {memory} bytes to summarise"
            )

        labels_started = time.monotonic()
        groups, orders = _cell_orders(populations, contacts, labels_of)
        logger.info(
            f"LFP report {label}: groups { ({a: len(g) for a, g in groups.items()}) }, found in"
            f" {duration(time.monotonic() - labels_started)}"
        )
        if memory is not None:
            if (
                move_for_groups
                and peak_bytes(steps, contacts, sum(len(g) for g in groups.values())) > memory
            ):
                raise OverMemoryError(
                    f"{steps} steps x {contacts} contacts by group take over {memory} bytes"
                )
            groups = _axes_in_memory(groups, steps, contacts, memory)

        total = np.zeros((steps, contacts), np.float64)
        fields = {
            axis: GroupFields(names_, np.zeros((steps, len(names_), contacts), np.float32))
            for axis, names_ in groups.items()
        }
        progress = ReadProgress(
            label, sum(p.data.size * p.data.dtype.itemsize for p in populations)
        )
        for population in populations:
            kept = {a: o for a, o in orders[population.name].items() if a in fields}
            _sum_population(population, read, total, fields, kept, progress, workers=workers)
        progress.finish()
        if not np.isfinite(total).all():
            raise _unreadable("The report has values that are not finite")

    return SummedReport(
        populations=names, start=float(times[0]), dt=float(times[2]), total=total, fields=fields
    )


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
    low, high = values.min(axis=0), values.max(axis=0)
    return np.stack(
        [
            low,
            high,
            high - low,
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
    quarter = min(WELCH_MAX_SEGMENT, 2 ** int(np.floor(np.log2(max(1, steps / 4)))))
    n = min(steps, max(WELCH_SEGMENT, quarter))
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


def overview_level(steps: int) -> int:
    """The k at which 2**k steps a bin gets under MAX_OVERVIEW_STEPS, as the halving does."""
    k = 0
    while math.ceil(steps / 2**k) > MAX_OVERVIEW_STEPS:
        k += 1
    return k


def mean_level(level0: np.ndarray, k: int) -> np.ndarray:
    """The mean of each 2**k steps of contact x step, a last shorter bin as it comes."""
    starts = np.arange(0, level0.shape[-1], 2**k)
    counts = np.diff(np.r_[starts, level0.shape[-1]])
    summed = np.add.reduceat(level0, starts, axis=-1, dtype=np.int64)
    return np.round(summed / counts).astype(np.int16)


def log_bands(psd: np.ndarray, frequencies: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A spectrum's means over PSD_BANDS bands of equal width on a log axis, 0 Hz left out."""
    if len(frequencies) <= PSD_BANDS + 1:
        return psd, frequencies
    above_zero = frequencies[1:]
    edges = np.geomspace(above_zero[0], above_zero[-1], PSD_BANDS + 1)
    bands = np.minimum(np.searchsorted(edges, above_zero, side="right") - 1, PSD_BANDS - 1)
    starts = np.flatnonzero(np.r_[True, np.diff(bands) != 0])
    counts = np.diff(np.r_[starts, len(above_zero)])
    means = np.add.reduceat(psd[..., 1:], starts, axis=-1, dtype=np.float64) / counts
    return means.astype(np.float32), np.add.reduceat(above_zero, starts) / counts


def share_of_total(values: np.ndarray, total: np.ndarray) -> float:
    """How much of the total's variance a group's field accounts for, steps x contacts both. The
    groups' shares add up to 1, and one working against the rest has a negative share.
    """
    centred = total - total.mean(axis=0)
    power = float((centred * centred).sum())
    if power == 0:
        return 0.0
    return float(((values - values.mean(axis=0)) * centred).sum()) / power


def deflated_row(row: np.ndarray) -> bytes:
    """A row of int16 as HDF5's shuffle and deflate filters leave it."""
    shuffled = np.frombuffer(row.astype("<i2").tobytes(), np.uint8).reshape(-1, 2).T
    return zlib.compress(shuffled.tobytes(), DEFLATE_LEVEL)


def _write_chunks(dataset: h5py.Dataset, group: int, rows: np.ndarray) -> None:
    # Written deflated, or HDF5 would keep a row that doesn't shrink as it is and flag it in the
    # chunk's filter mask, for the browser to tell apart
    with ThreadPoolExecutor(DEFLATES_AT_ONCE) as pool:
        for contact, chunk in enumerate(pool.map(deflated_row, rows)):
            dataset.id.write_direct_chunk((group, contact, 0), chunk, 0)


def _chunk_table(dataset: h5py.Dataset) -> np.ndarray:
    groups, contacts, _ = dataset.shape
    table = np.zeros((groups, contacts, 2), np.uint64)

    def note(chunk) -> None:
        group, contact, _ = chunk.chunk_offset
        table[group, contact] = chunk.byte_offset, chunk.size

    dataset.id.chunk_iter(note)
    return table


def _write_group_axis(
    h5: h5py.File,
    axis: str,
    fields: GroupFields,
    report: SummedReport,
    written: dict[str, h5py.Dataset],
) -> dict:
    steps, groups, contacts = fields.values.shape
    k = overview_level(steps)
    name = f"lfp/{axis}"
    levels: list[dict] = [{"step": 1, "kind": "value", "dataset": f"/{name}/level0"}]
    overview = None
    if k == 0:
        level0 = written[f"/{name}/level0"] = h5.create_dataset(
            f"{name}/level0", (groups, contacts, steps), "<i2"
        )
    else:
        # Not listed in the index's datasets: it has no one offset
        level0 = h5.create_dataset(
            f"{name}/level0",
            (groups, contacts, steps),
            "<i2",
            chunks=(1, 1, steps),
            compression="gzip",
            compression_opts=DEFLATE_LEVEL,
            shuffle=True,
        )
        bins = math.ceil(steps / 2**k)
        overview = written[f"/{name}/level{k}"] = h5.create_dataset(
            f"{name}/level{k}", (groups, contacts, bins), "<i2"
        )
        levels[0]["chunks"] = f"/{name}/chunks"
        levels.append({"step": 2**k, "kind": "mean", "dataset": f"/{name}/level{k}"})

    scales, shares, stats, spectra = [], [], [], []
    frequencies = np.zeros(0)
    for group in range(groups):
        # One group at a time: a segment of the spectra over all of them could take tens of GB
        values = fields.values[:, group : group + 1, :]
        rows, scale = quantize(values)
        scales.append(float(scale[0]))
        shares.append(share_of_total(values[:, 0, :], report.total))
        stats.append(contact_stats(values, report.start, report.dt)[0])
        psd, fine = welch(values, report.dt)
        band_psd, frequencies = log_bands(psd[0], fine)
        spectra.append(band_psd)
        if overview is None:
            level0[group] = rows[0]
        else:
            _write_chunks(level0, group, rows[0])
            overview[group] = mean_level(rows[0], k)

    if overview is not None:
        written[f"/{name}/chunks"] = h5.create_dataset(f"{name}/chunks", data=_chunk_table(level0))
    written[f"/{name}/stats"] = h5.create_dataset(f"{name}/stats", data=np.stack(stats))
    written[f"/{name}/psd"] = h5.create_dataset(f"{name}/psd", data=np.stack(spectra))
    return {
        "name": axis,
        "groups": fields.groups,
        "scales": scales,
        "shares": shares,
        "levels": levels,
        "stats": f"/{name}/stats",
        "psd": f"/{name}/psd",
        "psd_frequencies": [float(f) for f in frequencies],
    }


def _write_total(h5: h5py.File, report: SummedReport, written: dict[str, h5py.Dataset]) -> dict:
    values = report.total[:, None, :]
    level0, scales = quantize(values)
    written["/lfp/total/level0"] = h5.create_dataset("lfp/total/level0", data=level0)
    levels = min_max_levels(level0)
    for k, level in levels:
        written[f"/lfp/total/level{k}"] = h5.create_dataset(f"lfp/total/level{k}", data=level)
    written["/lfp/total/stats"] = h5.create_dataset(
        "lfp/total/stats", data=contact_stats(values, report.start, report.dt)
    )
    psd, frequencies = welch(values, report.dt)
    written["/lfp/total/psd"] = h5.create_dataset("lfp/total/psd", data=psd)
    return {
        "name": "total",
        "groups": ["total"],
        "scales": [float(s) for s in scales],
        "levels": [
            {"step": 1, "kind": "value", "dataset": "/lfp/total/level0"},
            *(
                {"step": 2**k, "kind": "min_max", "dataset": f"/lfp/total/level{k}"}
                for k, _ in levels
            ),
        ],
        "stats": "/lfp/total/stats",
        "psd": "/lfp/total/psd",
        "psd_frequencies": [float(f) for f in frequencies],
    }


def write_summary(report: SummedReport, h5_path: Path, *, version: int, source: dict) -> dict:
    """Write the summary's h5 at `h5_path`. Returns its index."""
    start, dt = report.start, report.dt
    steps, contacts = report.total.shape
    written: dict[str, h5py.Dataset] = {}
    with h5py.File(h5_path, "w", libver="latest") as h5:
        axes = [_write_total(h5, report, written)]
        written["/lfp/correlation"] = h5.create_dataset(
            "lfp/correlation", data=correlation(report.total)
        )
        for axis, fields in report.fields.items():
            axes.append(_write_group_axis(h5, axis, fields, report, written))
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
        "axes": axes,
        "correlation": {"dataset": "/lfp/correlation", "scale": 1 / 32767},
        "datasets": datasets,
    }


def _inflated_row(chunk: bytes) -> np.ndarray:
    """What a browser does to a chunk: deflate undone, then shuffle."""
    bytes_ = np.frombuffer(zlib.decompress(chunk), np.uint8)
    return bytes_.reshape(2, -1).T.ravel().view("<i2")


def verify(h5_path: Path, index: dict) -> None:
    """Every dataset read as raw bytes at its offset equals the dataset, and so does every chunk of
    the rows of a group's field, read the same way and undone as a browser does.
    """
    raw = np.memmap(h5_path, dtype=np.uint8, mode="r")
    with h5py.File(h5_path, "r") as h5:
        for name, d in index["datasets"].items():
            dtype = np.dtype(d["dtype"])
            n = int(np.prod(d["shape"])) * dtype.itemsize
            view = raw[d["offset"] : d["offset"] + n].view(dtype).reshape(d["shape"])
            if not np.array_equal(view, _dataset(h5, name)[:]):
                raise AssertionError(f"{name} is not where the index says it is")
        for axis in index["axes"]:
            level0 = axis["levels"][0]
            if "chunks" not in level0:
                continue
            rows = _dataset(h5, level0["dataset"])
            table = _dataset(h5, level0["chunks"])[:]
            for (group, contact), (offset, size) in zip(
                np.ndindex(table.shape[:2]), table.reshape(-1, 2).tolist(), strict=True
            ):
                row = _inflated_row(raw[offset : offset + size].tobytes())
                if not np.array_equal(row, rows[group, contact]):
                    raise AssertionError(f"{axis['name']} row {group}, {contact} is not there")
