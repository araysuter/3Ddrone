# Operations and recovery

## Prerequisites

Use Ubuntu 24.04 with Docker Engine and Compose v2, an NVIDIA driver compatible with the CUDA runtime pinned by `gpu.Dockerfile`, and NVIDIA Container Toolkit. Verify Docker GPU access before building:

```bash
nvidia-smi
docker run --rm --gpus '"device=0"' nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

The first ODM and Splatfacto image builds are large and can take a long time. Keep at least 10 GB of host RAM free for Ubuntu and application services. The API derives ODM concurrency from image megapixels, logical cores, and the remaining memory.

## Start and stop

```bash
make build
make up
docker compose ps
make logs
make down
```

`docker compose down` preserves all bind-mounted project data. Do not add `-v` unless you have separately verified what Docker will remove.

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

Nginx and API logs use Docker’s configured log driver. NodeODM also keeps its own rotating logs under the retained data root. Check usage regularly:

```bash
docker compose logs --tail=300 api nodeodm splat-worker
du -sh /srv/local-aerial-mapper/*
```

Projects are never automatically deleted. Use the confirmed UI deletion only after downloading or backing up anything that must be retained.

## Updating upstream

The configured `upstream` remote is OpenDroneMap/ODM. Do not casually merge a new ODM release into the processing branch. First:

1. Build and run the unmodified new official GPU baseline against the sample.
2. Check NodeODM option metadata and API compatibility.
3. Run Standard full-output acceptance.
4. Run the splat conversion and memory test.
5. Only then merge the new tag and update notices.
