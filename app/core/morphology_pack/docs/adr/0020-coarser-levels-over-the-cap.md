# 0020. Over the cap, a circuit is built again at the coarser two levels

- Status: Accepted. Changes what a circuit over the cap gets in [0017](0017-memory-cap.md) and [0019](0019-built-on-demand-in-bluenaas.md), and adds a second set of levels to [0005](0005-three-levels.md).
- Date: 2026-11-04, the user's word

## Context

A circuit over the cap on `4cpu-16gb` got a `.no-pack` marker and kept its somas. The male CNS, 164,606 neurons, is one: it is within `MAX_NEURONS` and over `MAX_SEGMENTS` at three levels.

Its segments, built locally on 2026-11-04. The build at three levels was run with the limit lifted and stopped at 314.3M, at cell 144,067, so the finest level and the total are estimates:

| Level | Segments |
| --- | --- |
| Finest, 0.125 µm | about 190M, estimated |
| Middle, 0.25 µm | 147.0M |
| Far, 1 µm | 31.1M |
| All three | about 368M, estimated |
| The coarser two | 178.1M |

At the coarser two levels it is a pack of 532 MB, and the viewer drew it at 60 fps on an M4 Pro ([performance.md](../performance.md#the-male-cns-at-two-levels)). The format and both readers go by the levels the index lists, so neither changed.

## Decision

- A build at `LEVELS` that goes over the cap on `4cpu-16gb` is built again at `COARSER_LEVELS`, the middle and far levels, with the cap worked out again. Over the cap there too, `.no-pack` says too large, as before.
- On `low` nothing changes: a build over its share moves to `4cpu-16gb`, where this applies.
- It applies to every circuit, fly or rat, the user's word.
- `MAX_SEGMENTS` and `BYTES_A_SEGMENT` stay as they are.
- The web app keeps up to 1 GiB of packs in its browser cache, up from 500 MiB, which this pack did not fit. The user's word; a change in that repository.

## Alternatives weighed

| Option | What it gave against the chosen | Verdict |
| --- | --- | --- |
| No pack over the cap, as before | The male CNS keeps its somas, with no morphologies at any distance | Replaced |
| `MAX_SEGMENTS` raised, three levels kept | The finest level close up. About 368M segments, about 23 GiB at the rate measured here, so a larger task. Its pack's size and how the viewer holds it are not measured | Rejected |
| Fly circuits only | A rat circuit over the cap keeps its somas rather than a coarser close view, and the build needs to know the species | Rejected, the user's word |
| The first attempt's work kept for the second | About 185 s of the male CNS's 488 s. The attempt stops part way and holds 11.4 GiB, a level of it to be dropped | Not built |

## Consequences

- Close up, such a circuit is drawn within 0.25 µm, not 0.125 µm. On the fly sample that is 97.6% of the length kept against 99.4%, and 19.4% of traced points off by more than their radius against 4.2%.
- A circuit over the cap pays for the attempt that fails first, about 185 s of 488 s on the male CNS. The memory is back before the second attempt: its cap was still 300M.
- `pack.json` does not say how many levels a pack has. That is in the pack's index and the build's log.
- A `.no-pack` from before this decision stays until the cache is cleared, so clear it once this is deployed.
- **The slope is under what the male CNS measured.** Its peak was 12,094 MiB in 15.6 GiB, about 67 B a segment past the base, against `BYTES_A_SEGMENT`'s 50. That leaves room at two levels. The cause is not established, and the rate comes from one circuit at two levels.
- **A build that runs out of memory gets no second attempt.** At 67 B a segment, three levels between about 246M and 300M pass the cap and do not fit 16 GiB. The kernel kills the build and it ends `failed` rather than at two levels. The whole FlyWire brain, about 255M by estimate and never built, falls in that range, so [0017](0017-memory-cap.md)'s claim that it fits is unproven. The same goes for a circuit over the cap at three levels and between about 246M and 300M at two: it used to get a clean `.no-pack`, and now fails. Either way the build is retried once, reported `failed` for a day and can then be queued again. `BYTES_A_SEGMENT` at 67 would send the first kind to two levels and the second to `.no-pack`; not done, because one measurement does not settle it.
- **What has been run.** `_pack_of` on a kept stage of the male CNS, on 4 CPUs in a VM of 15.6 GiB, not from a queue. Its pack is the same to the byte as the one the viewer drew. No rat circuit over the cap has been built at two levels, and a pack this size has not been served from staging.
