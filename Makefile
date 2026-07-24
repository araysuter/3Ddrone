.PHONY: build host-check up down logs demo gpu-smoke test

build:
	docker compose --profile build-only build odm-gpu
	docker compose build nodeodm splat-worker api frontend

host-check:
	./scripts/check-host.sh

up: host-check
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs --tail=200 -f

demo:
	docker compose -f compose.yaml -f compose.demo.yaml up -d --build

gpu-smoke:
	docker compose run --rm nodeodm nvidia-smi
	docker compose run --rm splat-worker nvidia-smi

test:
	PYTHONPATH=services/api python3 -m pytest services/api/tests
	npm --prefix frontend run build
