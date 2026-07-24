.PHONY: build build-images odm-base rebuild-odm config-check host-check up down logs demo gpu-smoke test

build: config-check build-images

build-images: odm-base
	docker compose build nodeodm splat-worker api frontend

odm-base:
	@if docker image inspect local-aerial-mapper/odm:3.6.0-gpu >/dev/null 2>&1; then \
		echo "Using existing pinned ODM 3.6.0 GPU image."; \
	else \
		docker compose --profile build-only build odm-gpu; \
	fi

rebuild-odm: config-check
	docker compose --profile build-only build odm-gpu

config-check:
	./scripts/check-config.sh
	docker compose config --quiet

host-check:
	./scripts/check-host.sh

up: config-check
	./scripts/check-host.sh
	$(MAKE) build-images
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
