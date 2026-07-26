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

## Public read-only sharing

Do this only after the exact source revision being deployed has been pushed to
the public AGPL repository. The sharing profile does not expose the private
frontend: Cloudflare can reach only a dedicated public Nginx gateway, and that
gateway proxies only the anonymous share API.

1. Enable public sharing in `.env`:

   ```dotenv
   MAPPER_SHARING_ENABLED=true
   MAPPER_PUBLIC_BASE_URL=https://dronemaps.ashersuter.com
   COMPOSE_PROFILES=sharing
   ```

2. In Cloudflare Zero Trust, create a new remotely managed tunnel dedicated to
   this application. Add the public hostname `dronemaps.ashersuter.com` and set
   its service URL to:

   ```text
   http://public-gateway:8080
   ```

   Do not point the hostname at `frontend`, `api`, port 8000, or the host's
   Tailscale address.

3. Copy only the tunnel connector token into `.env`:

   ```dotenv
   CLOUDFLARE_TUNNEL_TOKEN=paste-the-connector-token-here
   ```

   Do not commit `.env`, generated map links, or the tunnel token. The pinned
   cloudflared container reads the token from
   `TUNNEL_TOKEN`; no Cloudflare credentials file is mounted.

4. Validate and start:

   ```bash
   MAPPER_ENV_FILE=.env ./scripts/check-config.sh
   docker compose --profile sharing config --quiet
   make up
   docker compose ps
   docker compose logs --tail=100 public-gateway cloudflared
   ```

5. Verify the boundary before creating a link:

   ```bash
   curl --fail https://dronemaps.ashersuter.com/healthz
   curl -i https://dronemaps.ashersuter.com/api/projects
   curl -i https://dronemaps.ashersuter.com/api/setup
   curl -i https://dronemaps.ashersuter.com/api/system
   ```

   Health must return 200 and every private API probe must return 404. The bare
   hostname must show “A valid share link is required.” Confirm separately that
   the Tailscale operator URL still supports login and processing.

Map and Project Share dialogs warn that links grant anonymous viewing and
downloads, report aggregate page views and the last view time, and can disable
or replace the bearer UUID. Links do not expire automatically. Named Projects
also report published and failed map counts, the last publication, and offer
Retry publishing for isolated item failures.

Individual-map links are `/share/maps/{uuid}`. Project collections are
`/share/projects/{uuid}`, with reloadable selections at
`/share/projects/{uuid}/maps/{itemUuid}`. Existing `/share/{uuid}` links are
retired and must be copied again from their owner dialogs after this upgrade.

During reprocessing, the previous published output remains public; a completed
replacement atomically supersedes it. A new usable partial result can publish,
but a partial or failed replacement never displaces a prior Project snapshot.
Stop the profile with `make down`, or remove `sharing` from
`COMPOSE_PROFILES` and run `make up`; disabling either kind of link is
immediate and does not require a container restart.

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
- Splat worker restart: `running` becomes `queued`; optional COLMAP output,
  ODM conversion, and Nerfstudio checkpoints remain in `splat/work`.
- Splat failure: project becomes `partial`; ODM outputs stay available and only the splat stage can be retried.
- Optional COLMAP exporter failure: the worker logs the exporter tail and
  continues through Nerfstudio's ODM converter; use **Retry splat** on projects
  created before this behavior was installed.
- Splatfacto initialization remains offline. Its LPIPS/AlexNet weights are
  baked into `/opt/torch-cache`; a runtime `urllib` or DNS error means the
  splat image predates that cache and must be rebuilt with `make up`.
- Full 3D mesh cleanup failure: the API retries the same NodeODM task once with ODM's 2.5D terrain mesh and reuses completed reconstruction work.
- Other ODM failure, or a failed terrain-mesh recovery: inspect NodeODM console lines in the project log before changing any parameters.

The processing stage list and completed-results tabs contain only the products
selected for that project. With Gaussian splat disabled, the footer reads
`ODM only`, no splat stage is submitted, and no splat viewer or stale splat
artifact is served. Disabling an output also removes its NodeODM archive paths
and native ODM export flags where supported. Shared prerequisites can still
run—for example, ODM needs dense reconstruction and a terrain surface to
produce an orthomosaic.

Each new run writes a mapper log line confirming the effective preset,
feature/point-cloud quality, rolling-shutter flag, and readout accepted by
NodeODM, followed by the enabled output names. For an FC330 High run it must report `preset=high`,
`feature-quality=ultra`, `pc-quality=high`, `rolling-shutter=True`, and
`rolling-shutter-readout=33ms`. The API fails closed if NodeODM does not retain
the requested options.

## Logs and disk

All container logs use Docker JSON-file rotation (three 50 MiB files per
container). NodeODM also keeps three rotating 50 MiB application logs under
`$MAPPER_DATA_DIR/logs/nodeodm`. Check usage regularly:

```bash
docker compose logs --tail=300 api nodeodm splat-worker
du -sh /srv/local-aerial-mapper/*
```

Maps are never automatically deleted. Use the confirmed map deletion only
after downloading or backing up anything that must be retained. Deleting an
organizational project is nondestructive: its maps return to No Project.

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
When sharing is selected, it also requires the exact HTTPS public origin, a
third distinct signing key, a non-placeholder Cloudflare connector token, and
the `sharing` Compose profile.
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
