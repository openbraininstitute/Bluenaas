# 0019. Built on demand in Bluenaas and kept in its cache; no stored asset

- Status: Accepted. Supersedes [0014](0014-stored-as-a-circuit-asset.md) and [0015](0015-built-in-the-asset-job.md).
- Date: 2026-10-28, the user's word

## Context

A pack built in the circuit asset job ([0015](0015-built-in-the-asset-job.md)) and stored as an asset ([0014](0014-stored-as-a-circuit-asset.md)) reaches only the circuits that job runs for. The circuits registered before needed a backfill, and only members of a circuit's project may add an asset to it, so a public circuit seen from another project could not have one built for its viewer.

Bluenaas already keeps caches on EFS by epoch, clears them from an admin route, runs jobs on RQ queues sized per worker group, and starts batch workers when a queue fills up. Its workers stage circuits through entitysdk with the user's token, so a build there reads any circuit the user can read.

## Decision

- The package moves to Bluenaas, `app/core/morphology_pack/`, with its tests and these docs.
- A pack is built the first time a viewer asks for it, `POST /circuit/{id}/morphology-pack`, and kept in the `morphology-pack` cache until the cache is cleared. `GET` on the same path serves it from there. Nothing is stored on the circuit.
- The build is sized by the circuit's neuron count, with one retry:
  - over 160,000 neurons, it is refused and nothing is queued;
  - up to 2,000, it runs on `low`, in one worker's share of a shared task;
  - above that, or when a build on `low` goes over its share, on `4cpu-16gb`, a batch worker of its own size, one worker a task.
- A build on `4cpu-16gb` over the cap, or of a circuit with no morphologies, leaves a `.no-pack` marker with the reason, so it is never tried again in that epoch.
- Pair and small circuits are staged whole into the circuit cache, as their simulations stage them. Larger ones are staged partially, on the task's own disk, and deleted after the build.

## Alternatives weighed

| Option | What it gave against the chosen | Verdict |
| --- | --- | --- |
| In the asset job, stored as an asset ([0015](0015-built-in-the-asset-job.md)) | A pack at once for a circuit registered after the release. A backfill for the others, nothing for a public circuit of another project, an upload to keep | Superseded |
| Built on demand, stored as an asset | The same write rights as above | Rejected |
| A gate by scale | Registration calls every circuit over 20 neurons a microcircuit unless overridden | Rejected for the neuron count |
| A partial stage on EFS | No disk to size on the task, a sweep after a killed task | Rejected for local disk, 100 GiB on `4cpu-16gb` |

## Consequences

- The first view of a circuit with no pack shows its somas, or for pair and small circuits a morphology a cell, while the build runs. Pair and small circuits switch to the pack on the next visit.
- Clearing the cache rebuilds every pack on demand.
- The API reads the markers only. The build's failure callback, which frees the lock, imports nothing of the worker, because the API runs it for a build whose worker died.
- The cap follows a worker's share of its task ([0017](0017-memory-cap.md)).
