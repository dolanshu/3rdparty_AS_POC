# Makefile — day-to-day commands for the 3rd-party AS POC.
#
# Everything runs through uv so that the locked environment is used. The packages under
# src/ are put on the import path with PYTHONPATH; no wheel is built.

SHELL := /bin/bash
UV ?= uv
RUN := $(UV) run
ARGS ?=
PYTHONPATH_LOCAL := $(CURDIR)/src
export PYTHONPATH := $(PYTHONPATH_LOCAL)

.DEFAULT_GOAL := help
.PHONY: help sync dev as mock console fraud lint format type test unit integration e2e demo \
        demo-fraud probe probe-608 rules capture docker-up docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync: ## Install or sync the locked environment
	$(UV) sync

dev: sync ## Run the AS locally (mock and console follow in their milestones)
	$(RUN) python -m as_app.main

as: sync ## Run only the AS process
	$(RUN) python -m as_app.main

mock: sync ## Run only the mock S-SBC process (ARGS="--call +86216180001=+9991234567")
	$(RUN) python -m s_sbc_mock.main $(ARGS)

console: sync ## Run only the console process
	$(RUN) python -m console.main

fraud: sync ## Run only the anti-fraud AS process (listens on FRAUD_SIP_LISTEN_PORT, 5062)
	$(RUN) python -m anti_fraud_as.main

lint: sync ## ruff format --check + ruff check + mypy
	$(RUN) ruff format --check .
	$(RUN) ruff check .
	$(RUN) mypy

format: sync ## Apply ruff formatting
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

type: sync ## Type check only
	$(RUN) mypy

test: unit integration e2e ## All three layers

unit: sync ## Unit layer: pure logic, no sockets
	$(RUN) pytest tests/unit -m unit

integration: sync ## Integration layer: localhost UDP
	$(RUN) pytest tests/integration -m integration

e2e: sync ## E2E layer: complete call flows
	$(RUN) pytest tests/e2e -m e2e

demo: sync ## Place one real trunk call and narrate the translation on the wire
	$(RUN) python tools/demo_call.py --rules-file config/routing_rules.yaml

demo-fraud: sync ## Screening demo: one allowed call and one call rejected with 608
	$(RUN) python tools/demo_fraud_call.py --screening-file config/caller_screening.yaml

rules: sync ## Show the active rule set and the decision for the sample numbers
	$(RUN) python tools/show_rules.py --rules-file config/routing_rules.yaml

capture: sync ## Complete one call and capture its messages as samples
	$(RUN) python tools/capture_call.py

probe: sync ## Probe the sippy stack and print what it really does
	$(RUN) python tools/sippy_probe.py

probe-608: sync ## Probe the sippy 608 Rejected path over real UDP (ADR-0007 design evidence)
	$(RUN) python tools/anti_fraud_probe.py

docker-up: ## Start the local demo stack (both AS instances, two mocks, console)
	docker compose -f deploy/docker-compose.yml up --build

docker-down: ## Stop the compose stack
	docker compose -f deploy/docker-compose.yml down

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
