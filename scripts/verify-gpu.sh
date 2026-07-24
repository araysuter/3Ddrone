#!/usr/bin/env bash
set -euo pipefail

docker compose exec -T nodeodm nvidia-smi --id=0
docker compose exec -T splat-worker nvidia-smi --id=0
docker compose exec -T splat-worker python3 -c 'import torch; print(torch.cuda.get_device_name(0)); print(torch.cuda.mem_get_info())'
docker compose exec -T nodeodm python3 -c 'from opendm import gpu; print("ODM GPU module import: ok")'

echo "GPU visibility passed. Confirm CUDA SIFT and OpenMVS use in a real project log."
