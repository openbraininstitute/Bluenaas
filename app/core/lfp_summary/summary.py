"""The summary of a SONATA LFP report, per-cell or summed, in the format the web app's viewer reads.

One HDF5 file plus a JSON index of its datasets' byte offsets, so a browser reads any slice with an
HTTP Range request and no HDF5 library. The format is specified in docs/format.md.
"""

import math
import time
import zlib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np
from loguru import logger

from app.core.lfp_summary.nodes import GROUP_COLUMNS
from app.core.lfp_summary.ranges import RangeFile, ReadRange
from app.domains.simulation_result.lfp_summary import NoSummaryReason

MAX_OVERVIEW_STEPS = 2048
# An overview level's bins are 4 times the next finer one's, the finest at least this many steps
LEVEL_STEP_BITS = 2
MIN_LEVEL_STEPS = 16
# Full-resolution rows are cut in blocks of this many steps, a power of two, so a window is read alone
BLOCK_STEPS = 1 << 16
# An overview level's bins are cut in tiles of this many, the unit a window of them is read in
TILE_BINS = 4096
STATS = ["min", "max", "ptp", "rms", "mean", "trough_ms"]
WELCH_SEGMENT = 256
# Else the index's frequencies and the spectra grow with the run
WELCH_MAX_SEGMENT = 1 << 16
PSD_BANDS = 128

DEFLATE_LEVEL = 6
# A block of rows is stored as its residuals of the order, under this, that deflate smallest
PREDICTOR_ORDERS = 3
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
# A group's field is set against the total in blocks of steps of about this size, in float64
SHARE_BLOCK_BYTES = 64 << 20

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
    # The axes the cells differ on that were not summed, and why
    axes_left_out: dict[str, str] = field(default_factory=dict)
    # Whether its cells could be grouped, given their labels: two or more, in order
    groupable: bool = False


@dataclass
class _Population:
    name: str
    data: h5py.Dataset
    element_ids: np.ndarray
    node_ids: np.ndarray
    index_pointers: np.ndarray | None
    to_uv: float

    @property
    def cells(self) -> int:
        return len(self.node_ids)

    def is_regular(self, contacts: int) -> bool:
        """Every cell on every contact, in order, and the cells' columns in the order of `node_ids`."""
        return (
            len(self.element_ids) == self.cells * contacts
            and self.index_pointers is not None
            and np.array_equal(self.index_pointers, contacts * np.arange(self.cells + 1))
            and bool((self.element_ids.reshape(self.cells, contacts) == np.arange(contacts)).all())
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


def _population(name: str, group: h5py.Group) -> _Population:
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
    index_pointers = group.get("mapping/index_pointers")
    return _Population(
        name=name,
        data=data,
        element_ids=element_ids,
        node_ids=np.asarray(_dataset(group, "mapping/node_ids")[:]),
        index_pointers=(
            np.asarray(index_pointers[:]) if isinstance(index_pointers, h5py.Dataset) else None
        ),
        to_uv=TO_UV[units],
    )


def _cell_orders(
    populations: list[_Population], labels_of: CellLabels, regular: bool
) -> tuple[dict[str, list[str]], dict[str, dict[str, _CellOrder]]]:
    """The groups of each axis the cells differ on, and the order of each population's cells for
    it. Only an axis every population has: its groups must add up to the total. None where the cells
    are not all on all contacts in the order of their ids, as the groups go by that, which is no
    report that is written, and saves a slower sum.
    """
    groups = {}
    orders: dict[str, dict[str, _CellOrder]] = {p.name: {} for p in populations}
    if not regular:
        logger.warning("The cells of an LFP report are not in order, so it has no groups")
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
    groups: dict[str, list[str]], steps: int, contacts: int, memory: int, move_for_groups: bool
) -> dict[str, list[str]]:
    """The axes that fit: the largest are left out first, as they cost the most. None are left out
    if `move_for_groups`: it raises instead.
    """
    kept = dict(groups)
    while peak_bytes(steps, contacts, sum(len(g) for g in kept.values())) > memory:
        if move_for_groups:
            raise OverMemoryError(
                f"{steps} steps x {contacts} contacts by group take over {memory} bytes"
            )
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
        populations = [_population(name, _group(report, name)) for name in names]
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
        regular = all(p.is_regular(contacts) for p in populations)
        groups, orders = _cell_orders(populations, labels_of, regular)
        logger.info(
            f"LFP report {label}: groups { ({a: len(g) for a, g in groups.items()}) }, found in"
            f" {duration(time.monotonic() - labels_started)}"
        )
        found = groups
        if memory is not None:
            groups = _axes_in_memory(groups, steps, contacts, memory, move_for_groups)

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
        populations=names,
        start=float(times[0]),
        dt=float(times[2]),
        total=total,
        fields=fields,
        axes_left_out={axis: "memory" for axis in found if axis not in fields},
        groupable=regular and sum(p.cells for p in populations) > 1,
    )


def _scale_of(peak: float) -> float:
    return peak / 32767 if peak > 0 else 1.0


def _to_int16(values: np.ndarray, scale: float) -> np.ndarray:
    q = np.divide(values, scale, dtype=np.float64)
    np.round(q, out=q)
    np.clip(q, -32767, 32767, out=q)
    return q.astype(np.int16)


def overview_level(steps: int) -> int:
    """The k at which bins of 2**k steps come under MAX_OVERVIEW_STEPS."""
    k = 0
    while math.ceil(steps / 2**k) > MAX_OVERVIEW_STEPS:
        k += 1
    return k


def overview_levels(steps: int) -> list[int]:
    """The k of each overview level, finest first: only 0, the values, for a run of MAX_OVERVIEW_STEPS or fewer."""
    levels = [overview_level(steps)]
    while 2 ** (levels[0] - LEVEL_STEP_BITS) >= MIN_LEVEL_STEPS:
        levels.insert(0, levels[0] - LEVEL_STEP_BITS)
    return levels


def min_max_level(level0: np.ndarray, k: int) -> np.ndarray:
    """The min and max of each 2**k steps of contact x step, a last shorter bin as it comes."""
    starts = np.arange(0, level0.shape[-1], 2**k)
    return np.stack(
        [
            np.minimum.reduceat(level0, starts, axis=-1),
            np.maximum.reduceat(level0, starts, axis=-1),
        ],
        axis=-1,
    )


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


@dataclass
class Centred:
    """The total, steps x contacts, with its mean and its power at each contact: what each group's
    field is set against. It is centred a block at a time, as a copy would take as much as the total.
    """

    total: np.ndarray
    mean: np.ndarray
    power: np.ndarray

    @classmethod
    def of(cls, total: np.ndarray) -> "Centred":
        centred = cls(total, total.mean(axis=0), np.zeros(total.shape[1]))
        for _, block in centred.blocks():
            centred.power += np.einsum("tc,tc->c", block, block)
        return centred

    def blocks(self, fields: int = 1) -> Iterator[tuple[int, np.ndarray]]:
        """Blocks of steps of the centred total, as many as `fields` of them take SHARE_BLOCK_BYTES."""
        steps, contacts = self.total.shape
        rows = max(1, SHARE_BLOCK_BYTES // (8 * contacts * fields))
        for a in range(0, steps, rows):
            yield a, self.total[a : a + rows] - self.mean


def correlation(centred: Centred) -> np.ndarray:
    """Zero-lag Pearson correlation between contacts, as int16 / 32767."""
    contacts = len(centred.power)
    product = np.zeros((contacts, contacts))
    for _, block in centred.blocks():
        product += block.T @ block
    with np.errstate(divide="ignore", invalid="ignore"):
        c = product / np.sqrt(np.outer(centred.power, centred.power))
    return np.round(np.clip(np.nan_to_num(c), -1, 1) * 32767).astype(np.int16)


def mean_level(level0: np.ndarray, k: int) -> np.ndarray:
    """The mean of each 2**k steps of contact x step, a last shorter bin as it comes."""
    starts = np.arange(0, level0.shape[-1], 2**k)
    counts = np.diff(np.r_[starts, level0.shape[-1]])
    return np.add.reduceat(level0, starts, axis=-1, dtype=np.float64) / counts


def log_bands(psd: np.ndarray, frequencies: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A spectrum's means over PSD_BANDS bands of equal width on a log axis, 0 Hz left out."""
    if len(frequencies) <= PSD_BANDS + 1:
        return psd[..., 1:], frequencies[1:]
    above_zero = frequencies[1:]
    edges = np.geomspace(above_zero[0], above_zero[-1], PSD_BANDS + 1)
    bands = np.minimum(np.searchsorted(edges, above_zero, side="right") - 1, PSD_BANDS - 1)
    starts = np.flatnonzero(np.r_[True, np.diff(bands) != 0])
    counts = np.diff(np.r_[starts, len(above_zero)])
    means = np.add.reduceat(psd[..., 1:], starts, axis=-1, dtype=np.float64) / counts
    return means.astype(np.float32), np.add.reduceat(above_zero, starts) / counts


def covariance_with_total(values: np.ndarray, centred: Centred) -> np.ndarray:
    """Each group's field, steps x groups x contacts, summed against the centred total at each
    contact: groups x contacts. A group's own mean needs no taking off, as the centred total sums to
    0. In one pass for all the groups, as each pass centres the total again.
    """
    _, groups, contacts = values.shape
    covariance = np.zeros((groups, contacts))
    for a, total in centred.blocks(groups):
        block = np.asarray(values[a : a + len(total)], np.float64)
        covariance += np.einsum("tgc,tc->gc", block, total)
    return covariance


def shares_of_total(values: np.ndarray, centred: Centred) -> tuple[list[float], np.ndarray]:
    """How much of the total's variance each group's field accounts for, over all contacts and at
    each. The groups' shares add up to 1, and one working against the rest has a negative share. A
    contact with no variance gives none.
    """
    covariance = covariance_with_total(values, centred)
    power = float(centred.power.sum())
    at_contacts = np.divide(
        covariance, centred.power, out=np.zeros_like(covariance), where=centred.power > 0
    )
    shares = [float(c) / power if power else 0.0 for c in covariance.sum(axis=1)]
    return shares, at_contacts.astype(np.float32)


def deflated_row(row: np.ndarray) -> bytes:
    """A row of int16 as HDF5's shuffle and deflate filters leave it."""
    shuffled = np.frombuffer(row.astype("<i2").tobytes(), np.uint8).reshape(-1, 2).T
    return zlib.compress(shuffled.tobytes(), DEFLATE_LEVEL)


def residuals(row: np.ndarray, order: int) -> np.ndarray:
    """Each value less the one before, `order` times over, in int16 as it wraps."""
    for _ in range(order):
        row = np.diff(row, prepend=np.int16(0))
    return row


def undo_residuals(row: np.ndarray, order: int) -> np.ndarray:
    for _ in range(order):
        row = np.cumsum(row, dtype=np.int16)
    return row


def predicted_row(row: np.ndarray) -> tuple[int, bytes]:
    """A row as the residuals of the order that deflate smallest: the order, and the chunk."""
    candidates = [row]
    for _ in range(1, PREDICTOR_ORDERS):
        candidates.append(residuals(candidates[-1], 1))
    chunks = [deflated_row(candidate) for candidate in candidates]
    order = min(range(PREDICTOR_ORDERS), key=lambda o: len(chunks[o]))
    return order, chunks[order]


def unpredicted_row(row: np.ndarray) -> tuple[int, bytes]:
    return 0, deflated_row(row)


def _write_chunks(
    dataset: h5py.Dataset,
    pool: ThreadPoolExecutor,
    group: int,
    start: int,
    values: np.ndarray,
    scale: float,
    encode: Callable[[np.ndarray], tuple[int, bytes]] = unpredicted_row,
) -> np.ndarray:
    """Contacts' values from `start` in uV, chunk by chunk, to the group's scale: each chunk's
    order of prediction, contact x chunk.
    """
    # Written deflated, or HDF5 would keep a row that doesn't shrink as it is and flag it in the
    # chunk's filter mask, for the browser to tell apart. A last block is padded to the chunk's
    # length, as HDF5 stores an edge chunk whole, and predicted with its padding.
    assert dataset.chunks
    length = dataset.chunks[2]
    within = (0,) * (values.ndim - 2)
    orders = np.empty((values.shape[0], math.ceil(values.shape[1] / length)), np.uint8)
    for c, a in enumerate(range(0, values.shape[1], length)):
        rows = _to_int16(values[:, a : a + length], scale)
        if rows.shape[1] < length:
            pad = ((0, 0), (0, length - rows.shape[1])) + ((0, 0),) * len(within)
            rows = np.pad(rows, pad)
        for contact, (order, chunk) in enumerate(pool.map(encode, rows)):
            dataset.id.write_direct_chunk((group, contact, start + a, *within), chunk, 0)
            orders[contact, c] = order
    return orders


def _chunked(h5: h5py.File, path: str, shape: tuple[int, ...], length: int) -> h5py.Dataset:
    """An int16 dataset in chunks of `length` along its third axis, one group's contact's each."""
    return h5.create_dataset(
        path,
        shape,
        "<i2",
        chunks=(1, 1, length, *shape[3:]),
        compression="gzip",
        compression_opts=DEFLATE_LEVEL,
        shuffle=True,
    )


def _chunk_table(dataset: h5py.Dataset) -> np.ndarray:
    groups, contacts, steps = dataset.shape[:3]
    assert dataset.chunks
    length = dataset.chunks[2]
    table = np.zeros((groups, contacts, math.ceil(steps / length), 2), np.uint64)

    def note(chunk) -> None:
        group, contact, start = chunk.chunk_offset[:3]
        table[group, contact, start // length] = chunk.byte_offset, chunk.size

    dataset.id.chunk_iter(note)
    return table


def _write_blocks(
    values: np.ndarray,
    rows_set: h5py.Dataset,
    pool: ThreadPoolExecutor,
    group: int,
    kind: str,
    ks,
    scale: float,
) -> tuple[list[np.ndarray], np.ndarray]:
    """One group's rows in blocks at its scale: its overview levels in uV, finest first, and each
    block's order of prediction, contact x block. Taken a span of steps at a time that holds whole
    blocks and whole bins of every level.
    """
    steps, contacts = values.shape
    span = max(BLOCK_STEPS, 2 ** ks[-1])
    # A mean is kept in float64, as it is worked out
    in_uv = [
        np.empty(
            (contacts, math.ceil(steps / 2**k)) + ((2,) if kind == "min_max" else ()),
            np.float64 if kind == "mean" else values.dtype,
        )
        for k in ks
    ]
    orders = []
    for a in range(0, steps, span):
        rows = np.ascontiguousarray(values[a : a + span].T)
        for level, k in zip(in_uv, ks, strict=True):
            binned = OVERVIEWS[kind](rows, k)
            level[:, a >> k : (a >> k) + binned.shape[1]] = binned
        orders.append(_write_chunks(rows_set, pool, group, a, rows, scale, predicted_row))
    return in_uv, np.concatenate(orders, axis=1)


OVERVIEWS = {"min_max": min_max_level, "mean": mean_level, "value": lambda rows, k: rows}


def _write_axis(
    h5: h5py.File,
    axis: str,
    fields: GroupFields,
    report: SummedReport,
    centred: Centred,
    overview_kind: str,
) -> dict:
    steps, groups, contacts = fields.values.shape
    ks = overview_levels(steps)
    # A short run's only overview is its values
    kind = "value" if ks == [0] else overview_kind
    name = f"lfp/{axis}"
    block_steps = min(BLOCK_STEPS, steps)
    rows_set = _chunked(h5, f"{name}/rows", (groups, contacts, steps), block_steps)
    levels: list[dict] = [
        {
            "step": 1,
            "kind": "value",
            "dataset": f"/{name}/rows",
            "blocks": {
                "chunks": f"/{name}/chunks",
                "steps": block_steps,
                "predictors": f"/{name}/block_predictors",
            },
        }
    ]
    overviews = []
    for k in ks:
        bins = math.ceil(steps / 2**k)
        shape = (groups, contacts, bins) + ((2,) if kind == "min_max" else ())
        tile = min(TILE_BINS, bins)
        overviews.append(_chunked(h5, f"{name}/level{k}", shape, tile))
        levels.append(
            {
                "step": 2**k,
                "kind": kind,
                "dataset": f"/{name}/level{k}",
                "blocks": {"chunks": f"/{name}/level{k}_chunks", "steps": tile},
            }
        )

    shares, contact_shares = shares_of_total(fields.values, centred)
    scales, stats, spectra, block_predictors = [], [], [], []
    frequencies = np.zeros(0)
    with ThreadPoolExecutor(DEFLATES_AT_ONCE) as pool:
        for group in range(groups):
            # One group at a time: a segment of the spectra over all of them could take tens of GB
            values = fields.values[:, group : group + 1, :]
            stats.append(contact_stats(values, report.start, report.dt)[0])
            psd, fine = welch(values, report.dt)
            band_psd, frequencies = log_bands(psd[0], fine)
            spectra.append(band_psd)
            # To the peak of the rows, not of the levels', from their min and max
            scale = _scale_of(max(float(stats[-1][:, 1].max()), -float(stats[-1][:, 0].min())))
            scales.append(scale)
            in_uv, orders = _write_blocks(values[:, 0], rows_set, pool, group, kind, ks, scale)
            block_predictors.append(orders)
            for overview, level in zip(overviews, in_uv, strict=True):
                _write_chunks(overview, pool, group, 0, level, scale)

    h5.create_dataset(f"{name}/chunks", data=_chunk_table(rows_set))
    for k, overview in zip(ks, overviews, strict=True):
        h5.create_dataset(f"{name}/level{k}_chunks", data=_chunk_table(overview))
    h5.create_dataset(f"{name}/block_predictors", data=np.stack(block_predictors))
    h5.create_dataset(f"{name}/stats", data=np.stack(stats))
    h5.create_dataset(f"{name}/psd", data=np.stack(spectra))
    h5.create_dataset(f"{name}/contact_shares", data=contact_shares)
    return {
        "name": axis,
        "groups": fields.groups,
        "scales": scales,
        "shares": shares,
        "levels": levels,
        "stats": f"/{name}/stats",
        "psd": f"/{name}/psd",
        "psd_frequencies": [float(f) for f in frequencies],
        "contact_shares": f"/{name}/contact_shares",
    }


def _contiguous_datasets(h5: h5py.File) -> dict[str, dict]:
    """Where each dataset lies in the file. One in chunks has no one offset, so it isn't listed."""
    datasets = {}

    def note(name: str, node: h5py.Dataset | h5py.Group) -> None:
        if isinstance(node, h5py.Dataset) and node.chunks is None:
            datasets[f"/{name}"] = {
                "offset": int(node.id.get_offset()),
                "shape": list(node.shape),
                "dtype": node.dtype.str,
            }

    h5.visititems(note)
    return datasets


def write_summary(
    report: SummedReport,
    h5_path: Path,
    *,
    version: int,
    source: dict,
    groups_unavailable: str | None = None,
) -> dict:
    """Write the summary's h5 at `h5_path`. Returns its index. `groups_unavailable` says why the
    report has no groups where that is not down to the report itself.
    """
    centred = Centred.of(report.total)
    with h5py.File(h5_path, "w", libver="latest") as h5:
        total = GroupFields(["total"], report.total[:, None, :])
        axes = [_write_axis(h5, "total", total, report, centred, "min_max")]
        axes += [
            _write_axis(h5, axis, fields, report, centred, "mean")
            for axis, fields in report.fields.items()
        ]
        h5.create_dataset("lfp/total/correlation", data=correlation(centred)[None])
        axes[0]["correlation"] = {"dataset": "/lfp/total/correlation", "scale": 1 / 32767}
        h5.flush()
        datasets = _contiguous_datasets(h5)

    return {
        "format": "lfp-summary",
        "version": version,
        "source": source,
        "populations": report.populations,
        "time": {"start": report.start, "dt": report.dt, "steps": report.total.shape[0]},
        "units": "uV",
        "contacts": report.total.shape[1],
        "stats": STATS,
        "axes": axes,
        "axes_left_out": report.axes_left_out,
        "groups_unavailable": groups_unavailable,
        "datasets": datasets,
    }


def _inflated_row(chunk: bytes) -> np.ndarray:
    """What a browser does to a chunk: deflate undone, then shuffle."""
    bytes_ = np.frombuffer(zlib.decompress(chunk), np.uint8)
    return bytes_.reshape(2, -1).T.ravel().view("<i2")


def _rows_add_up_to_the_overview(h5: h5py.File, raw: np.ndarray, axis: dict) -> None:
    """Each group's first contact's row, as a browser reads it, its blocks' residuals added back up
    by their orders, binned as the finest overview level is: within an int16 step of it, as each
    rounds the same values once. A block at the wrong order is far off."""
    rows, finest = axis["levels"][0], axis["levels"][1]
    table = _dataset(h5, rows["blocks"]["chunks"])[:]
    predictors = rows["blocks"].get("predictors")
    orders = _dataset(h5, predictors)[:] if predictors else np.zeros(table.shape[:3], np.uint8)
    steps = _dataset(h5, rows["dataset"]).shape[2]
    k = int(finest["step"]).bit_length() - 1
    for group, scale in enumerate(axis["scales"]):
        blocks = []
        for block in range(table.shape[2]):
            offset, size = table[group, 0, block].tolist()
            residuals = _inflated_row(raw[offset : offset + size].tobytes())
            blocks.append(undo_residuals(residuals, int(orders[group, 0, block])))
        row = np.concatenate(blocks)[:steps] * scale
        binned = OVERVIEWS[finest["kind"]](row[None], k)[0]
        stored = _dataset(h5, finest["dataset"])[group, 0] * scale
        if np.abs(binned - stored).max() > scale * 1.01:
            raise AssertionError(f"{axis['name']} group {group}: its rows are not its overview")


def verify(h5_path: Path, index: dict) -> None:
    """Every dataset read as raw bytes at its offset equals the dataset; every chunk of the rows and
    of the overview levels of a group's field is where its table says; the first contact's, and
    every contact's last, inflated as a browser does, are what HDF5 reads, and their padding comes
    back zero; and the first contact's rows add up to its overview.
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
            for level in axis["levels"]:
                chunked = _dataset(h5, level["dataset"])
                table = _dataset(h5, level["blocks"]["chunks"])[:]
                length = level["blocks"]["steps"]
                predictors = level["blocks"].get("predictors")
                orders = _dataset(h5, predictors)[:] if predictors else None
                within = (0,) * (chunked.ndim - 3)
                last = table.shape[2] - 1
                for group, contact, block in np.ndindex(table.shape[:3]):
                    offset, size = table[group, contact, block].tolist()
                    a = block * length
                    chunk = raw[offset : offset + size].tobytes()
                    there = chunked.id.read_direct_chunk((group, contact, a, *within))[1] == chunk
                    if there and (contact == 0 or block == last):
                        stored = chunked[group, contact, a : a + length].ravel()
                        read = _inflated_row(chunk)
                        order = 0 if orders is None else int(orders[group, contact, block])
                        values = undo_residuals(read, order)
                        there = (
                            np.array_equal(read[: len(stored)], stored)
                            and not values[len(stored) :].any()
                        )
                    if not there:
                        raise AssertionError(
                            f"{level['dataset']} {group}, {contact} block {block} is not there"
                        )
            _rows_add_up_to_the_overview(h5, raw, axis)
