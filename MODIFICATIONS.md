# Local Aerial Mapper modifications

This repository combines OpenDroneMap with a local application layer. The following is the modification notice required for a clear AGPL source handoff.

## Upstream foundations

- OpenDroneMap was merged from the official `v3.6.0` tag. No processing algorithm or stage under `opendm/`, `stages/`, `run.py`, `gpu.Dockerfile`, or `SuperBuild/` has been modified by the mapper application.
- NodeODM was vendored from the official `v2.2.3` tag at commit `baa619a9fd42bf32daf45fc03257f8e9b92449d4`. Its application source is unchanged.
- The original ODM README is retained at `docs/upstream/ODM-README.md`.

## Added application code

- `frontend/`: React/Vite workstation UI and Nginx reverse proxy.
- `services/api/`: authentication, SQLite metadata, resumable intake, project orchestration, NodeODM client, SSE, artifacts, raster sampling, and host telemetry.
- `services/splat/`: OpenSfM-to-COLMAP conversion, checkpoint-aware regular Splatfacto training, PLY export, Spark SPZ compression, and scene-transform retention.
- `compose.yaml`: local-only four-service deployment and GPU device 0 reservations.
- `docs/`, `scripts/`, tests, build helpers, and operator configuration.

The only upstream-root adjustment outside these additions is `.gitignore`, which retains the local sample dataset and application runtime products outside Git.
