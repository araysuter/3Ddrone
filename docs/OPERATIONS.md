# Operations and recovery

## Prerequisites

Use Ubuntu 24.04 with Docker Engine and Compose v2, an NVIDIA driver compatible with the CUDA runtime pinned by `gpu.Dockerfile`, and NVIDIA Container Toolkit. Configure Docker and verify GPU access before building:

```bash
nvidia-smi
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus '"device=0"' nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
make host-check
```

The first ODM and Splatfacto image builds are large and can take a long time. Keep at least 10 GB of host RAM free for Ubuntu and application services. The API derives ODM concurrency from image megapixels, logical cores, and the remaining memory.

## Start and stop

```bash
make up
docker compose ps
make logs
make down
```

`make up` validates `.env`, performs the Ubuntu/GPU preflight, builds all pinned
images, starts the stack, and waits for service health. `make build` remains
available when an operator wants to separate the long first build from startup.
Once `local-aerial-mapper/odm:3.6.0-gpu` exists, ordinary application pulls
reuse it rather than recompiling ODM. Run `make rebuild-odm` only when
`gpu.Dockerfile`, ODM itself, or its native dependencies intentionally change.
`docker compose down` preserves all bind-mounted project data. Do not add `-v` unless you have separately verified what Docker will remove.

For a CPU-only UI/API check on macOS or Linux:

```bash
make demo
curl --fail http://127.0.0.1:8080/api/health
make down
```

Demo mode does not start NodeODM or Splatfacto and does not prove the mapping
pipeline.

### Missing NVIDIA persistence socket

If container startup fails with:

```text
failed to fulfil mount request: open /run/nvidia-persistenced/socket: no such file or directory
```

the host NVIDIA runtime is incomplete. The preflight now catches this before
any long image build. First inspect why the daemon could not start:

```bash
sudo systemctl status nvidia-persistenced --no-pager -l
sudo journalctl -u nvidia-persistenced -n 100 --no-pager
```

If host `nvidia-smi` succeeds and the preflight lists a generated CDI
specification under `/etc/cdi` or `/var/run/cdi`, refresh it:

```bash
sudo systemctl restart nvidia-cdi-refresh.service
nvidia-ctk --debug cdi list
sudo systemctl restart docker
make host-check
```

NVIDIA Container Toolkit 1.18 and newer normally manages
`/var/run/cdi/nvidia.yaml` through `nvidia-cdi-refresh`. On an older toolkit,
regenerate the specific CDI file printed by the preflight with:

```bash
sudo nvidia-ctk cdi generate --output=/path/printed/by/preflight
sudo systemctl restart docker
make host-check
```

If the configuration is current and the daemon is required, repair it and retry:

```bash
sudo systemctl restart nvidia-persistenced
test -S /run/nvidia-persistenced/socket
sudo systemctl restart docker
make host-check
make up
```

`nvidia-persistenced.service` is commonly a static helper unit and is not meant
to be enabled with `systemctl enable`; start or restart it only when the
installed NVIDIA runtime configuration actually references its socket. If the
unit is missing in that case, install the `nvidia-compute-utils` package
matching the installed driver version. Do not create an empty socket file; it
must be owned by the running NVIDIA daemon.

## Tailscale

The app is intentionally unreachable on LAN interfaces:

```bash
ss -ltnp | grep 8080
sudo tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

Tailscale terminates HTTPS and proxies to the local HTTP listener. Keep `MAPPER_COOKIE_SECURE=true` for this deployment. Direct `http://127.0.0.1:8080` setup requires temporarily setting it to `false`, and should not be used for remote access.

## Backups

Stop the application before a consistent cold backup:

```bash
docker compose stop
sudo rsync -aHAX --numeric-ids /srv/local-aerial-mapper/ /backup/local-aerial-mapper/
docker compose start
```

Restore the entire configured data directory, not just `mapper.sqlite3`; database rows refer to retained source, NodeODM tasks, extracted artifacts, and splat checkpoints.

## Recovery behavior

- Interrupted upload: choose the same local files in the same project session; the browser queries the durable offset and resumes.
- API restart during ODM: the saved NodeODM UUID is polled and the task continues.
- NodeODM restart: its task directory remains mounted and NodeODM reloads durable task data.
- Splat worker restart: `running` becomes `queued`; COLMAP output and Nerfstudio checkpoints remain in `splat/work`.
- Splat failure: project becomes `partial`; ODM outputs stay available and only the splat stage can be retried.
- ODM failure: inspect NodeODM console lines in the project log before changing any parameters.

## Logs and disk

All container logs use Docker JSON-file rotation (three 50 MiB files per
container). NodeODM also keeps three rotating 50 MiB application logs under
`$MAPPER_DATA_DIR/logs/nodeodm`. Check usage regularly:

```bash
docker compose logs --tail=300 api nodeodm splat-worker
du -sh /srv/local-aerial-mapper/*
```

Projects are never automatically deleted. Use the confirmed UI deletion only after downloading or backing up anything that must be retained.

Before diagnosing a container failure, validate the exact deployed
configuration:

```bash
MAPPER_ENV_FILE=.env ./scripts/check-config.sh
docker compose config --quiet
docker compose ps
docker compose logs --tail=300 api nodeodm splat-worker frontend
```

The configuration checker rejects relative or root data paths, placeholder,
short, or duplicate service tokens, root/out-of-range container IDs, and
invalid cookie/session/disk-reserve values before Docker mutates runtime state.
The default upload/extraction reserve is 5 GiB. Lower
`MAPPER_DISK_RESERVE_BYTES` only when the operator has deliberately accepted a
smaller safety margin; the API refuses values below 1 GiB.

## Updating upstream

The configured `upstream` remote is OpenDroneMap/ODM. Do not casually merge a new ODM release into the processing branch. First:

1. Build and run the unmodified new official GPU baseline against the sample.
2. Check NodeODM option metadata and API compatibility.
3. Run Standard full-output acceptance.
4. Run the splat conversion and memory test.
5. Only then merge the new tag and update notices.
