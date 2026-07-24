# Architecture and data contracts

## Runtime boundaries

Only Nginx binds a host port, and it binds `127.0.0.1:8080`. Nginx joins the
edge and internal networks; the API, NodeODM, and splat worker join only the
Docker `internal: true` network. NodeODM also requires its own random token; the
splat worker requires a different internal token. The browser never receives
either service token.

The API owns project state. NodeODM remains authoritative for ODM task progress and console output. The API uses only NodeODM’s initialize/upload/commit, info, output, cancel, restart, remove, options, and `all.zip` download routes. It does not mutate NodeODM task directories.

All long-running containers drop Linux capabilities and enable
`no-new-privileges`. Nginx uses its unprivileged image, while API and worker
processes run as the configured non-root UID/GID. The one-shot data initializer
has no network, a read-only root filesystem, and only the three capabilities
needed to create/chown retained directories. NodeODM application code remains
owned by root; only its task, temp, and rotating-log directories are writable
by its service user.

## Durable data layout

`MAPPER_DATA_DIR` is mounted at `/data` in the API and splat worker:

```text
source/<project UUID>/       Validated originals and support files
nodeodm/<task UUID>/         NodeODM-owned durable task state
splat/jobs/                  Durable splat job records
splat/work/<project UUID>/   Optional COLMAP export, ODM conversion, checkpoints, and recovery state
metadata/mapper.sqlite3      Users, sessions, projects, uploads, and SSE events
metadata/projects/<UUID>/    Extracted allowlisted artifacts and all.zip
logs/nodeodm/                NodeODM logs
uploads/                     Incomplete resumable parts
```

Deleting a project requires the exact project name in `X-Confirm-Project-Name`. The API rejects deletion while the project is active. No background retention policy removes completed project data.

NodeODM receives an effectively non-expiring task retention value because
upstream interprets zero as immediate deletion. Its temporary, uncommitted
uploads are still cleaned after seven days. Docker JSON logs and NodeODM file
logs rotate to bound routine log growth.

## Project state machine

```mermaid
stateDiagram-v2
    [*] --> uploading
    uploading --> queued: start
    queued --> processing: GPU lock acquired
    processing --> splatting: ODM completed
    processing --> completed: splat disabled
    processing --> failed: ODM failed
    processing --> canceled: cancel acknowledged
    splatting --> completed: PLY/SPZ exported
    splatting --> partial: splat failed
    partial --> splatting: retry splat
    failed --> queued: reprocess
    canceled --> queued: reprocess
```

There is one API job-runner task and NodeODM is configured with `parallelQueueProcessing=1`. The runner waits for ODM completion before it submits a splat job, so the two GPU-heavy workloads cannot overlap.

The splat image preloads Splatfacto's LPIPS/AlexNet metric weights into
`/opt/torch-cache` while the image is built. The running worker remains on the
internal network and does not need DNS or internet access to initialize
training.

Before uploading, the API reserves a UUID and sends it through NodeODM's
standard `Set-UUID` field. This makes a lost commit response recoverable: the
same durable UUID is polled rather than creating an ambiguous duplicate task.
Uncommitted temporary uploads are safe to retry and are eventually removed by
NodeODM. NodeODM's initialize endpoint accepts its fields as
`multipart/form-data`; immediately after commit, the API compares every
requested option with the effective task options and cancels the task if any
setting was silently dropped or changed.

On API restart, queued, processing, or splatting projects are reconciled.
Existing NodeODM UUIDs are polled instead of re-uploaded. Transient NodeODM and
splat polling failures use bounded retries rather than immediately failing a
project. The splat worker changes an interrupted `running` job back to `queued`,
reuses the OpenSfM data, optional COLMAP interchange output, and
ODM-to-Nerfstudio conversion, then resumes from the newest Nerfstudio
config/checkpoint when one exists. The native COLMAP exporter is nonblocking
because training consumes Nerfstudio's ODM conversion directly. Final splat
products are validated, fsynced, and atomically published so an interrupted
export cannot replace a prior good result with a partial one.

If OpenMVS fails while cleaning ODM's full 3D Poisson mesh, the orchestrator
uses NodeODM's standard restart API once with `skip-3dmodel`. ODM reuses its
completed reconstruction and produces the normal 2.5D textured terrain mesh,
orthophoto, elevation, point-cloud, report, and camera outputs. The terrain OBJ
and GLB are packaged and exposed under their actual `odm_texturing_25d` paths.
Any second mesh failure remains a failed project rather than entering a retry
loop.

## Intake

The browser uploads 5 MiB chunks with three-file concurrency and computes
incremental SHA-256 digests without buffering whole files. It stores the server
upload UUID locally, queries `HEAD /api/uploads/{id}` after a connection loss,
and resumes from the server offset. The server serializes concurrent chunks,
reconciles the database offset with the on-disk part, and requires a matching
digest. After the final rename, `HEAD` can recover the narrow crash window in
which the validated file exists but the database completion transaction did
not finish.

The server enforces filename, file-size, project-size, disk-reserve, signature,
image-dimension, and duplicate-hash limits before atomically retaining a
source. Missing validated sources cause inspection or processing to fail
explicitly rather than silently producing an incomplete map.

EXIF and DJI XMP are read with ExifTool in the container. FC330 is mapped to the ODM rolling-shutter database profile and an explicit 33 ms readout. `.lchm` is provenance only.

## Outputs and viewers

The API sends NodeODM an explicit archive path list derived from the project's
output selections. NodeODM's legacy post-processing layer is disabled so it
cannot silently re-enable COG, GLB, or EPT exports; ODM 3.6 receives the
selected native options directly. The API downloads the resulting `all.zip`
over NodeODM’s public API, fsyncs and validates the ZIP, limits entry count and
expanded size, rejects traversal, symlinks, and duplicate paths, extracts
atomically under the project artifact directory, and builds a canonical
server-side allowlist. Artifact discovery and viewer routes apply the same
selection again, so stale files from an earlier run cannot expose a disabled
product.

- Orthomosaic/DSM/DTM: OpenLayers and local static tiles.
- Point cloud: generated OGC 3D Tiles when present; otherwise a background
  Rust/WASM worker decodes ODM's LAS/LAZ 1.4 output without blocking the UI.
- Textured mesh: Three.js loads ODM's authoritative OBJ, MTL, and JPEG textures,
  with the Draco-compressed GLB or OGC 3D Tiles retained as fallbacks.
- Gaussian splat: Spark 2.1 loads SPZ or PLY, reports streaming progress, and
  fits the camera to the decoded Gaussian bounds after initialization.
- Report: same-origin embedded PDF.
- Elevation: raster sample in the project CRS using Rasterio.

Turning off a product removes its viewer, download entries, archive paths, and
ODM export flags where ODM provides one. Some reconstruction stages are shared:
feature matching and dense reconstruction are prerequisites for mapped
products, and ODM creates an internal 2.5D terrain surface for raster products
even when the exported 3D model is disabled. Gaussian splatting is independent
and is never submitted when its output switch is off.

Measurement tools display project-CRS distance and area. Consumer GPS is always labeled best effort. GCP-assisted projects still require report review; the app does not promote them to certified survey grade.

The Advanced drawer is populated from the running NodeODM option metadata, but
the server exposes only a small typed allowlist. Arbitrary paths, clusters,
stage reruns, copied task state, and resource/GSD bypass options never reach
NodeODM.
