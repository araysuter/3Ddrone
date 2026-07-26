# Local Aerial Mapper modifications

This repository combines OpenDroneMap with a local application layer. The following is the modification notice required for a clear AGPL source handoff.

## Upstream foundations

- OpenDroneMap was merged from the official `v3.6.0` tag. No processing algorithm or stage under `opendm/`, `stages/`, `run.py`, or `SuperBuild/` has been modified by the mapper application.
- `gpu.Dockerfile` backports the GPU container compatibility portion of upstream ODM commit `44e3ff6e` (CUDA 12.9.1, the runtime image, Python paths, and Ubuntu 24.04's TBB runtime package). This avoids OpenMVS compilation against CUDA 13, which removed `cuda_texture_types.h`.
- NodeODM was vendored from the official `v2.2.3` tag at commit `baa619a9fd42bf32daf45fc03257f8e9b92449d4`. Its standard task and output APIs remain the orchestrator boundary, but the vendored source is intentionally modified: remote ZIP ingestion, task webhooks, and S3 export are disabled; vulnerable direct dependencies were removed or upgraded; UUID and Python 3.12 import compatibility were updated; startup-helper errors are preserved; and a production lockfile was added.
- The original ODM README is retained at `docs/upstream/ODM-README.md`.

## Added application code

- `frontend/`: React/Vite workstation UI and Nginx reverse proxy, including
  LAS/LAZ 1.4 decoding in a Rust/WASM background worker, authoritative ODM
  OBJ/MTL/JPEG texture loading, and the local Three.js Draco decoder retained
  for ODM GLB fallback. Spark initialization is observed explicitly so splat
  load progress, failures, and camera fitting are visible instead of producing
  an unexplained blank canvas.
  A separate public-only build and Nginx gateway render revocable anonymous
  map and named-Project links without shipping operator screens or proxying
  private API routes.
- `services/api/`: authentication, SQLite metadata, resumable intake, project orchestration, NodeODM client, SSE, artifacts, raster sampling, and host telemetry.
  The application adds one-level map folders, nullable map assignment, and
  metadata-only organization APIs; deleting a folder unassigns its maps without
  deleting any processing data.
  Optional public shares use random UUID bearer links, sanitized metadata,
  aggregate access statistics, and versioned hard-link snapshots that preserve
  the last completed publication during reprocessing. Named-Project shares add
  live membership, isolated per-map publication and retry state, scoped public
  item UUIDs, and a read-only flat map sidebar without requiring a browser
  cookie.
  Mapper presets disable ODM edge cropping by default (`crop=0`). A project can
  be reprocessed with new preset, output, and allowlisted Advanced settings
  while retaining its validated source uploads and keeping the prior local
  artifacts until their replacement archive is safely installed.
- `services/splat/`: best-effort native OpenSfM-to-COLMAP interchange export,
  Nerfstudio's supported ODM camera conversion, checkpoint-aware regular
  Splatfacto training, PLY export, Spark SPZ compression, and scene-transform
  retention. A native COLMAP exporter failure is logged but cannot block the
  authoritative ODM camera conversion used for training. gsplat is pinned to
  commit `4d3a3b69db4de0326f983ccf7b7b255271a17b01`; the Spark compressor is pinned
  to `f22236f95fdd8078f0c12e3aab479523d401daf6`. The worker installs only Spark's
  runtime dependencies because Spark's repository-level install expects
  generated Rust/WASM development packages that are not committed in the
  release tag. Splatfacto's LPIPS/AlexNet weights are preloaded into the image
  so the intentionally isolated runtime does not make an external request.
- `docker/nodeodm.Dockerfile` and `docker/nodeodm-config.json`: reproducible production dependencies, unprivileged numeric runtime ownership that reuses a matching base-image UID/GID when present, token-aware health checking, read-only application code, and retained rotating NodeODM logs.
- `compose.yaml`: four core long-running services, an initialization helper,
  local-only host binding, isolated edge/internal networks, GPU device 0
  reservations, dropped capabilities, log rotation, and durable bind mounts.
  The opt-in `sharing` profile adds a read-only public gateway and pinned
  cloudflared connector on a separate network; cloudflared cannot reach any
  processing service directly.
- `docs/`, `scripts/`, tests, build helpers, and operator configuration.

The only upstream-root adjustment outside these additions is `.gitignore`, which retains the local sample dataset and application runtime products outside Git.
