# What the browser's reader relies on

The LFP viewer reads summaries in TypeScript, in core-web-app's `src/features/lfp-viewer/summary.ts`. [format.md](format.md) is the specification it is written from. This page lists what it also relies on, or checks and refuses. A change to the writer that breaks any of it breaks every viewer already deployed, whatever the version says.

## It refuses

| A summary that | Why |
| --- | --- |
| Has an index whose `format` is not `"lfp-summary"`, or whose `version` is not 2 | Not a summary, or one it would misread |
| Has an index missing a field it requires, or with one of the wrong kind | A malformed index. Among these: no axis, an axis with no group, fewer than two levels, a `kind` other than `value`, `mean` or `min_max`, a `dtype` other than `<i2`, `<f4`, `<u8` or `\|u1` |
| Is answered other than 206 to a range request | The whole file would be downloaded: the request is cancelled |
| Is answered without the bytes asked for | Cut short |
| Has a dataset the index names but does not list, or a slice outside a dataset's shape | The index at odds with itself |
| Is answered 412 | Built again since its status was read: the viewer asks for the status once, and reads the new one |

## It relies on

- **Unknown fields of the index are ignored.** The index's schema strips what it does not name. A new field must therefore be one a reader may do without, as [Growing the format](format.md#growing-the-format) asks.
- **Contiguous datasets in C order at their `offset`.** A group's slice of a dataset, `[group]`, is one range. A chunk table is read so, a group at a time.
- **Every chunk deflated, as a standard zlib stream, with the shuffle.** The viewer inflates through the browser's own `DecompressionStream('deflate')` and undoes the shuffle for 2-byte items. It does not read HDF5's filter mask, so a chunk stored raw would be misread.
- **The padding at the end of a row's last block.** The viewer cuts a block to its steps before adding its residuals back up. A predictor that looks ahead would be undone wrong.
- **One `blocks.steps` for every block of a level,** and `ceil(steps / step)` bins in a level.
- **The levels' order.** The rows come first, and the overviews finest to coarsest.
  - The viewer opens on the coarsest level, read whole for every contact, so it must stay small: 2,048 bins at most.
  - For a window, it draws the coarsest level with a bin a pixel or more, else the full rows.
- **The total as the first axis, with one group.** It holds the correlation.
- **A group's overview as means.** Several groups chosen together are drawn as their sum, added up from their means. Min and max would not add up.
- **The stats columns found by name,** in the index's `stats`. A column the viewer does not know is not shown.
- **`multipart/byteranges` answers.** The viewer reads a view's ranges in one request, so with one check of the user's access.
  - Ranges that touch or overlap are merged first.
  - At most 100 ranges go in a request, as Starlette answers more with the whole file.
- **The `ETag` being the status's `sha256`, quoted.** Every read of the index or the h5 sends it as `If-Match`.

## How it fetches and keeps a summary

- **The status.** The viewer asks for it with `POST`, every 5 s while it is `building`, and every minute while the open summary's `groups_unavailable` is set.
- **Opening.** Once the summary is ready, the viewer reads the index, then the total's coarsest level and its stats and spectra.
  - A group's fields and stats are read as they are chosen.
  - The rows are read for the window in view.
- **Limits.** A view reads 256 rows at most, a row being a contact of a chosen group. Past 64 MiB of decoded rows in a window, it draws a coarser level instead.
- **The cache.** Reads are kept in memory, keyed by the summary's `sha256`: rows and tiles for a minute after they are last used, the rest for 5 minutes. Nothing is kept across page loads.
