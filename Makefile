.PHONY: build config-check host-check up down logs demo gpu-smoke test

build: config-check
	docker compose --profile build-only build odm-gpu
	docker compose build nodeodm splat-worker api frontend

config-check:
	./scripts/check-config.sh
	docker compose config --quiet

host-check:
	./scripts/check-host.sh

up: config-check build
	./scripts/check-host.sh
	docker compose up -d --remove-orphans --wait --wait-timeout 300

down:
	docker compose down

logs:
	docker compose logs --tail=200 -f

demo:
	mkdir -p "$${MAPPER_DATA_DIR:-$(CURDIR)/data/demo}"
	MAPPER_DATA_DIR="$${MAPPER_DATA_DIR:-$(CURDIR)/data/demo}" \
	NODEODM_TOKEN="$${NODEODM_TOKEN:-demo-nodeodm-token-not-for-production}" \
	MAPPER_INTERNAL_TOKEN="$${MAPPER_INTERNAL_TOKEN:-demo-internal-token-not-for-production}" \
	MAPPER_UID="$${MAPPER_UID:-$$(id -u)}" \
	MAPPER_GID="$${MAPPER_GID:-$$(id -g)}" \
	docker compose -f compose.yaml -f compose.demo.yaml up -d --build --remove-orphans --wait --wait-timeout 120

gpu-smoke:
	docker compose run --rm --no-deps --entrypoint nvidia-smi nodeodm --id=0
	docker compose run --rm --no-deps --entrypoint nvidia-smi splat-worker --id=0

test:
	PYTHONPATH=services/api python3 -m pytest services/api/tests
	npm --prefix frontend run lint
	npm --prefix frontend run build
