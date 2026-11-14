export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.local/python
export UV_CACHE_DIR := $(CURDIR)/.local/cache/uv
export UV_PYTHON_BIN_DIR := $(CURDIR)/.local/bin
export UV_NATIVE_TLS := true
export UV_LINK_MODE := copy
export XDG_CACHE_HOME := $(CURDIR)/.local/cache
export MPLCONFIGDIR := $(CURDIR)/.local/cache/matplotlib
export DVC_NO_ANALYTICS := true
export DVC_SITE_CACHE_DIR := $(CURDIR)/.local/cache/dvc
export DVC_GLOBAL_CONFIG_DIR := $(CURDIR)/.local/config/dvc
export DVC_SYSTEM_CONFIG_DIR := $(CURDIR)/.local/config/dvc-system
# Also support macOS volumes that reapply hidden flags to editable-install .pth files.
export PYTHONPATH := $(CURDIR)/src
export KUBECONFIG := $(CURDIR)/.local/kubeconfig
export LOCAL_UID := $(shell id -u)
UV := .local/bin/uv
COMPOSE := docker compose --env-file /dev/null -p mlops-assignment3 -f infra/compose.yaml
# Preserve the selected local training image on subsequent service starts.
-include .local/airflow-image.mk
export AIRFLOW_IMAGE

.PHONY: tools setup check lint test config services cluster smoke data-bootstrap data-status train-models verify-mlflow
tools:
	./scripts/install-tools.sh
setup:
	$(UV) python install 3.12.12
	$(UV) sync --frozen
	.venv/bin/python scripts/repair-local-pth.py
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
data-bootstrap:
	$(UV) run --frozen python scripts/bootstrap-data.py
data-status:
	$(UV) run --frozen dvc status --json data/iris.csv.dvc
train-models:
	$(UV) run --frozen python scripts/train-models.py
verify-mlflow:
	$(UV) run --frozen python scripts/verify-mlflow.py

.PHONY: package-inference inference-image verify-inference
package-inference:
	$(UV) run --frozen python -c 'import subprocess,sys; sys.exit(subprocess.run([sys.executable,"scripts/package-inference.py"],timeout=120).returncode)'
inference-image: package-inference
	$(UV) run --frozen python scripts/build-inference.py
verify-inference:
	$(UV) run --frozen python scripts/verify-inference.py --image mlops-assignment3-inference:$(shell git rev-parse --short=12 HEAD)

.PHONY: deploy-kubernetes verify-kubernetes
deploy-kubernetes:
	$(UV) run --frozen python scripts/deploy-kubernetes.py
verify-kubernetes:
	$(UV) run --frozen python scripts/verify-kubernetes.py

.PHONY: airflow-image verify-airflow-dag
airflow-image:
	$(UV) run --frozen python scripts/build-airflow.py
verify-airflow-dag:
	$(UV) run --frozen python scripts/verify-airflow-dag.py
