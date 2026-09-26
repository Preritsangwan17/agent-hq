# Agent HQ — common tasks. `make up` / `make down` wrap start.sh / stop.sh.
PY := .venv/bin/python

.PHONY: up down dev test bench bench-full screens fmt mock-ats audit

up:
	./start.sh

down:
	./stop.sh

# Backend supervisor in the foreground + Vite dev server on :5173 (proxies /api to :8765).
dev:
	@trap 'kill 0' INT TERM; HQ_SKIP_WEB_BUILD=1 ./start.sh -f & npm --prefix web run dev; wait

test:
	$(PY) -m pytest -q

# Benchmark local models (quick ≈ 3 min/model) and re-assign roles. Stop the worker first (make down).
bench:
	$(PY) -m hq.models.benchmark --quick

bench-full:
	$(PY) -m hq.models.benchmark --full

# Local mock ATS on 127.0.0.1:8799 (enable "Mock ATS (local, dev)" in Settings › Sources to feed it into the pipeline).
mock-ats:
	$(PY) -m mock_ats

# Export the first 20 eligibility / pay verdicts to data/audit/verdicts.csv for a manual accuracy check.
audit:
	$(PY) -m hq.pipeline.audit

screens:
	npm --prefix web run screens --if-present

fmt:
	uvx ruff format hq tests
	npm --prefix web run fmt --if-present
