# The LFP summary format

A summary is an HDF5 file and a JSON index of it, served apart. `summary.write_summary` writes both and returns the index. `summary.verify` checks the file against it.

This page is the specification. What the browser's reader relies on beyond it is in [the reader's contract](reader-contract.md). Why it is so is in [the README](README.md#why-it-is-so).

## The file

The datasets lie under `/lfp/{axis}/`, one set for each axis: `total` first, then each group column the cells differ on. Numbers are little-endian. A dataset is one of two kinds:

- **Contiguous**, listed in the index's `datasets` with its `offset`, `shape` and `dtype`. Its bytes lie at `offset`, in C order, so a slice along its leading axes is one range of bytes.
- **Chunked**: the full rows and the overview levels. They are not in `datasets`, as a chunked dataset has no one offset. Each chunk is found by its chunk table, a contiguous dataset.

Every dataset's first two axes are group and contact.

## The index

From a run of 100,000 steps at 0.1 ms, on 4 contacts, with two m-types, `datasets` and `psd_frequencies` cut short:

```json
{
  "format": "lfp-summary",
  "version": 2,
  "source": { "asset_id": "…", "size": 123456789 },
  "populations": ["S1nonbarrel_neurons"],
  "time": { "start": 0.0, "dt": 0.1, "steps": 100000 },
  "units": "uV",
  "contacts": 4,
  "stats": ["min", "max", "ptp", "rms", "mean", "trough_ms"],
  "axes": [
    {
      "name": "total",
      "groups": ["total"],
      "scales": [0.002138],
      "shares": [1.0],
      "levels": [
        {
          "step": 1,
          "kind": "value",
          "dataset": "/lfp/total/rows",
          "blocks": {
            "chunks": "/lfp/total/chunks",
            "steps": 65536,
            "predictors": "/lfp/total/block_predictors"
          }
        },
        {
          "step": 16,
          "kind": "min_max",
          "dataset": "/lfp/total/level4",
          "blocks": { "chunks": "/lfp/total/level4_chunks", "steps": 4096 }
        },
        {
          "step": 64,
          "kind": "min_max",
          "dataset": "/lfp/total/level6",
          "blocks": { "chunks": "/lfp/total/level6_chunks", "steps": 1563 }
        }
      ],
      "stats": "/lfp/total/stats",
      "psd": "/lfp/total/psd",
      "psd_frequencies": [0.6103515625, 1.220703125, 1.8310546875],
      "contact_shares": "/lfp/total/contact_shares",
      "correlation": { "dataset": "/lfp/total/correlation", "scale": 3.0518509e-05 }
    },
    {
      "name": "mtype",
      "groups": ["L23_BP", "L5_TPC:A"],
      "scales": [0.00131, 0.001252],
      "shares": [0.5001, 0.4999],
      "levels": ["… as the total's, of kind mean, under /lfp/mtype/"],
      "stats": "/lfp/mtype/stats",
      "psd": "/lfp/mtype/psd",
      "psd_frequencies": [0.6103515625, 1.220703125, 1.8310546875],
      "contact_shares": "/lfp/mtype/contact_shares"
    }
  ],
  "axes_left_out": {},
  "groups_unavailable": null,
  "datasets": {
    "/lfp/total/chunks": { "offset": 849522, "shape": [1, 4, 2, 2], "dtype": "<u8" },
    "/lfp/total/stats": { "offset": 849850, "shape": [1, 4, 6], "dtype": "<f4" },
    "/lfp/total/psd": { "offset": 853618, "shape": [1, 4, 104], "dtype": "<f4" }
  }
}
```

| Field | Meaning |
| --- | --- |
| `format`, `version` | `"lfp-summary"`, 2 |
| `source` | The report's asset id and size in bytes |
| `populations` | The report's populations, in its order |
| `time` | `start` and `dt` in ms, and the number of `steps` |
| `units` | `"uV"`: every value is in µV |
| `contacts` | The number of contacts |
| `stats` | The names of the columns of each axis's `stats` |
| `axes` | The total, then one axis for each group column the cells differ on |
| `axes_left_out` | The axes the cells differ on that the build left out, and why: `"memory"` |
| `groups_unavailable` | Why there are no groups where that is not down to the report: `"circuit_not_readable"`, or null |
| `datasets` | Every contiguous dataset by its path: `offset` in bytes, `shape`, `dtype` (`<i2`, `<f4`, `<u8` or `\|u1`) |

An axis:

| Field | Meaning |
| --- | --- |
| `name` | `total`, `mtype`, `etype`, `synapse_class`, `layer` or `region` |
| `groups` | Its groups, sorted by name. The total's one group is `total` |
| `scales` | µV per int16 unit, one per group: the group's peak over its rows / 32767, or 1 where it is 0 |
| `shares` | Each group's part of the total's variance over all contacts. They add up to 1 |
| `levels` | The full rows, then the overview levels, finest to coarsest |
| `stats`, `psd`, `contact_shares` | The paths of those datasets |
| `psd_frequencies` | The frequency of each value of `psd`, in Hz |
| `correlation` | The total's only: the dataset's path, and its `scale` (1/32767) |

A level:

| Field | Meaning |
| --- | --- |
| `step` | Steps a bin: 1 for the rows, 2^k for `level{k}` |
| `kind` | `value` for the rows and a short run's only overview, `min_max` for the total's overviews, `mean` for a group's |
| `dataset` | Its chunked dataset |
| `blocks.chunks` | Its chunk table |
| `blocks.steps` | Steps (for the rows) or bins (for an overview) a block holds |
| `blocks.predictors` | The rows' only: the dataset of each block's order |
| `blocks.scales` | Optional: a dataset of each block's own scale, group × contact × block, float32, for a writer that can't know the peak up front. This writer doesn't write it |

## The datasets

For an axis of G groups, on C contacts, over N steps:

| Dataset | Type | Shape | Content |
| --- | --- | --- | --- |
| `rows` | int16, chunked | G × C × N | The full rows, in blocks of `blocks.steps` (2^16, or N where shorter) of one contact, as residuals |
| `chunks` | uint64 | G × C × blocks × 2 | Each block's byte offset and size in the file |
| `block_predictors` | uint8 | G × C × blocks | Each block's order: 0, 1 or 2 |
| `level{k}` | int16, chunked | G × C × bins × 2 for `min_max`, G × C × bins otherwise | An overview of bins of 2^k steps, in tiles of `blocks.steps` bins of one contact |
| `level{k}_chunks` | uint64 | G × C × tiles × 2 | Each tile's byte offset and size |
| `stats` | float32 | G × C × 6 | The index's `stats`, from the rows in µV before they are rounded |
| `psd` | float32 | G × C × frequencies | The Welch spectrum, µV²/Hz |
| `contact_shares` | float32 | G × C | Each group's part of the total's variance at each contact |
| `correlation` | int16 | 1 × C × C | The total's only: zero-lag Pearson correlation × 32767 |

## Reading a block

A block of the rows, or a tile of a level, is one HDF5 chunk, written with `write_direct_chunk` and found by its table:

1. Its `offset` and `size` at `[group, contact, block]` of the table.
2. Its bytes inflated: a zlib stream, deflate at level 6.
3. HDF5's shuffle undone, for 2-byte items. The first half of the bytes are the values' low bytes, the second half their high bytes. A tile of a `min_max` level holds its bins' min and max, one after the other.
4. For a block of the rows, its residuals added back up, as many times as its order says: a running sum, wrapping as int16 does. The residuals were taken from 0 before the first value, over the whole block, padding included. A tile is order 0.
5. The padding dropped: the last block of a row is padded with zeros to the full length, as HDF5 stores an edge chunk whole. Block b holds steps `b × blocks.steps` up to `(b + 1) × blocks.steps` or N. A running sum only looks back, so the padding may be dropped before step 4.
6. Times the group's scale, in µV, or the block's own where `blocks.scales` gives one.

Order 1 keeps each value less the one before. Order 2 does that again. The writer tries all three for each block and keeps the one that deflates smallest.

## The overview levels

- **Which levels.**
  - The coarsest is the smallest k at which N / 2^k comes to 2,048 bins or fewer.
  - Finer ones follow at k − 2, k − 4 and so on, while 2^k is 16 steps or more.
  - A run of 2,048 steps or fewer has one overview, `level0`, its values, of kind `value`. Its index then has two levels of `step` 1, the rows and `level0`, as an axis always has the rows and an overview.
- **A bin** is 2^k steps from step 0, and the last is shorter where N doesn't divide.
  - `min_max` holds its min and its max.
  - `mean` holds its mean, worked out in float64.
  - Each level is at its group's scale, rounded and clipped to ±32767.
- **A tile** is `min(4096, bins)` bins of one contact. The last one is padded as a row's last block is.

## The statistics

- **`stats`**, per group and contact:
  - `min`, `max` and `ptp` (max − min);
  - `rms`, the root of the mean square, not centred;
  - `mean`;
  - `trough_ms`, the time of the min, in ms.
- **`psd`**, the one-sided Welch density:
  - a Hann window, half overlap, each segment's mean taken off;
  - its segment is a quarter of the run as a power of two, at least 256 steps and at most 2^16, and at most the run;
  - averaged over 128 bands of equal width on a log axis above 0 Hz, a band with no frequency left out, so there may be fewer;
  - `psd_frequencies` are each band's mean frequency;
  - a spectrum of 129 frequencies or fewer is kept as it is, without its 0 Hz.
- **`contact_shares`** are a group's covariance with the centred total over the total's variance at each contact.
  - A contact's groups add up to 1.
  - A group working against the rest has a negative share.
  - A contact with no variance gives 0.

## Growing the format

So that summaries already written keep being read, and readers already deployed keep reading new ones:

- Something new is an optional field of the index, or a new dataset that a field of the index names. Its absence means it is not known.
- A reader ignores the fields of the index it does not know.
- A field keeps its meaning. Another meaning is another field.
- The version goes up only for a change a reader of the version before would misread, such as a block's encoding or a unit. A reader refuses a version it does not know.
- A new version is built into a cache directory of its own, so every summary is built again in it as it is asked for.

## Changes to the format

| Version | Change |
| --- | --- |
| 1 | Bluenaas#195. Every dataset contiguous and uncompressed: the total alone, its rows whole as `level0`, overviews of min and max at half the steps each, and the float32 total in V under `/report` |
| 2 | The groups' fields, `shares`, `contact_shares`, `axes_left_out` and `groups_unavailable`. Rows in blocks of 2^16 steps with their orders, levels at 4 times the steps each in tiles, both found by chunk tables. Spectra in up to 128 log bands. The correlation at `/lfp/total/correlation`, 1 × C × C, named by the total's `correlation`. No `/report` |
