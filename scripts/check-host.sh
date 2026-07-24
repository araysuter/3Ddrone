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
socket_references=()
for config_root in /etc/cdi /var/run/cdi /etc/nvidia-container-runtime; do
    if [[ ! -d "$config_root" ]]; then
        continue
    fi

    while IFS= read -r reference; do
        [[ -n "$reference" ]] && socket_references+=("$reference")
    done < <(grep -R -s -l -- "$socket_path" "$config_root" 2>/dev/null || true)
done

if (( ${#socket_references[@]} > 0 )) && [[ ! -S "$socket_path" ]]; then
    cat >&2 <<'EOF'
Host GPU preflight failed: NVIDIA Container Toolkit is configured to mount
/run/nvidia-persistenced/socket, but that socket does not exist.
EOF

    printf '\nConfiguration files referencing the missing socket:\n' >&2
    printf '  %s\n' "${socket_references[@]}" >&2

    cat >&2 <<'EOF'

First inspect why the daemon could not start:

  sudo systemctl status nvidia-persistenced --no-pager -l
  sudo journalctl -u nvidia-persistenced -n 100 --no-pager

If host `nvidia-smi` works and the listed file is a generated CDI specification,
refresh the specification before retrying:

  sudo systemctl restart nvidia-cdi-refresh.service
  nvidia-ctk --debug cdi list
  sudo systemctl restart docker

Otherwise repair and start the persistence daemon:

  sudo systemctl restart nvidia-persistenced
  sudo systemctl restart docker

The CDI refresh service is provided by NVIDIA Container Toolkit 1.18 and newer.
On an older toolkit, regenerate the NVIDIA CDI file shown above with
`nvidia-ctk cdi generate --output=<that-cdi-file>`. Do not create an empty
socket file; it must be owned by the running NVIDIA daemon.
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
