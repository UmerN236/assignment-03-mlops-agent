export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.local/python
export UV_CACHE_DIR := $(CURDIR)/.local/cache/uv
export UV_PYTHON_BIN_DIR := $(CURDIR)/.local/bin
export UV_NATIVE_TLS := true
export UV_LINK_MODE := copy
export XDG_CACHE_HOME := $(CURDIR)/.local/cache
export MPLCONFIGDIR := $(CURDIR)/.local/cache/matplotlib
export DVC_NO_ANALYTICS := true
export KUBECONFIG := $(CURDIR)/.local/kubeconfig
export LOCAL_UID := $(shell id -u)
UV := .local/bin/uv
COMPOSE := docker compose --env-file /dev/null -p mlops-assignment3 -f infra/compose.yaml

.PHONY: tools setup check lint test config services cluster smoke
tools:
	./scripts/install-tools.sh
setup:
	$(UV) python install 3.12.12
	$(UV) sync --frozen
lint:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .
test:
	$(UV) run --frozen pytest
check: lint test
config:
	$(UV) run --frozen mlops-config
services:
	$(UV) run --frozen python scripts/prepare-runtime.py
	$(COMPOSE) up -d
cluster:
	./scripts/bootstrap-cluster.sh
smoke:
	$(UV) run --frozen python scripts/smoke-services.py
