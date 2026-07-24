#!/usr/bin/env bash
set -euo pipefail

fail() {
    echo "Host GPU preflight failed: $1" >&2
    exit 1
}

if [[ "$(uname -s)" != "Linux" ]]; then
    fail "the production stack requires the Ubuntu NVIDIA host"
fi

command -v docker >/dev/null 2>&1 || fail "Docker Engine is not installed"
docker info >/dev/null 2>&1 || fail "Docker is not running or this user cannot access its socket"
command -v nvidia-smi >/dev/null 2>&1 || fail "the NVIDIA driver utilities are not installed"
nvidia-smi >/dev/null 2>&1 || fail "the NVIDIA driver cannot communicate with GPU 0"

socket_path=/run/nvidia-persistenced/socket
socket_is_configured=false
for config_root in /etc/cdi /var/run/cdi /etc/nvidia-container-runtime; do
    if [[ -d "$config_root" ]] \
        && grep -R -s -q "$socket_path" "$config_root"; then
        socket_is_configured=true
        break
    fi
done

if [[ "$socket_is_configured" == true && ! -S "$socket_path" ]]; then
    cat >&2 <<'EOF'
Host GPU preflight failed: NVIDIA Container Toolkit is configured to mount
/run/nvidia-persistenced/socket, but that socket does not exist.

Repair it on Ubuntu, then rerun `make up`:

  sudo systemctl enable --now nvidia-persistenced
  sudo systemctl restart docker

If the service unit is missing, install the nvidia-compute-utils package that
matches the installed NVIDIA driver, then enable the service.
EOF
    exit 1
fi

odm_image=local-aerial-mapper/odm:3.6.0-gpu
if docker image inspect "$odm_image" >/dev/null 2>&1; then
    smoke_output="$(
        docker run --rm --gpus "device=0" --entrypoint nvidia-smi \
            "$odm_image" --id=0 2>&1
    )" || {
        echo "$smoke_output" >&2
        fail "Docker cannot start an NVIDIA container; repair the NVIDIA Container Toolkit"
    }
fi

echo "Host GPU preflight passed."
