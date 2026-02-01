#-------------------------------------------------------------
# CrowdPay Connect - Makefile
#
# This Makefile orchestrates all common developer-facing tasks
# for the CrowdPay Connect platform, including:
#   – Virtual-env/bootstrap
#   – Static analysis & security scanning
#   – Test/coverage
#   – Database migrations & seed data
#   – Proto/GRPC stub generation
#   – Docker lifecycle helpers
#
# Usage examples:
#   make            # -> show help
#   make setup      # -> bootstrap local dev env
#   make lint test  # -> run static analysis + unit tests
#
# The file is intentionally POSIX-shell-compatible for maximal
# portability. Whenever possible we rely solely on standard GNU
# tooling to avoid hidden dependencies.
#-------------------------------------------------------------

#-------------------------------------
# Configurable variables
#-------------------------------------
APP_NAME        := crowdpay_connect
PYTHON_VERSION  := 3.11

# Virtual-env layout
VENV_DIR        := .venv
VENV_BIN        := $(VENV_DIR)/bin
PIP             := $(VENV_BIN)/pip
PYTHON          := $(VENV_BIN)/python

# Paths
SRC_DIRS        := $(APP_NAME) tests
REQ_FILE        := requirements/dev.txt

# Docker
DOCKER_IMAGE    := $(APP_NAME)-svc
DOCKER_TAG      := latest
COMPOSE_FILE    := docker/docker-compose.yml

# Generic flags (settable from CLI, e.g. `make VERBOSE=1 test`)
CI              ?= 0
VERBOSE         ?= 0
COLOR           ?= always

ifeq ($(VERBOSE),1)
    Q :=
else
    Q := @
endif

#-------------------------------------
# Default target
#-------------------------------------
.DEFAULT_GOAL := help

#-------------------------------------
# Helper for coloured output
#-------------------------------------
define PRINT_HELP_PYSCRIPT
import re, sys, textwrap
for line in sys.stdin:
    match = re.match(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', line)
    if match:
        target, help = match.groups()
        print(f"  \033[36m{target:15}\033[0m {help}")
endef

#-------------------------------------
# Bootstrap targets
#-------------------------------------
$(VENV_DIR)/bin/activate: $(REQ_FILE) ## Create & update local virtual-env
	$(Q)echo "➤ Creating virtual environment (if needed)…"
	$(Q)test -d $(VENV_DIR) || python$(PYTHON_VERSION) -m venv $(VENV_DIR)
	$(Q)$(PIP) install --upgrade pip wheel
	$(Q)$(PIP) install -r $(REQ_FILE)
	$(Q)touch $@

setup: $(VENV_DIR)/bin/activate  ## Bootstrap local development environment

clean: ## Remove build artefacts & caches
	$(Q)echo "➤ Cleaning workspace…"
	$(Q)find . -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' | xargs -r rm -rf
	$(Q)rm -rf .coverage htmlcov dist build *.egg-info .mypy_cache .pytest_cache
	$(Q)rm -rf $(VENV_DIR)

#-------------------------------------
# Linting / Static Analysis
#-------------------------------------
lint: | $(VENV_DIR)/bin/activate  ## Run all linters & security scanners
	$(Q)echo "➤ Running black…"
	$(Q)$(VENV_BIN)/black --check --diff $(SRC_DIRS)
	$(Q)echo "➤ Running flake8…"
	$(Q)$(VENV_BIN)/flake8 $(SRC_DIRS)
	$(Q)echo "➤ Running mypy…"
	$(Q)$(VENV_BIN)/mypy $(SRC_DIRS)
	$(Q)echo "➤ Running bandit…"
	$(Q)$(VENV_BIN)/bandit -r $(SRC_DIRS) -ll

format: | $(VENV_DIR)/bin/activate  ## Auto-format using black & isort
	$(Q)$(VENV_BIN)/black $(SRC_DIRS)
	$(Q)$(VENV_BIN)/isort $(SRC_DIRS)

#-------------------------------------
# Tests & coverage
#-------------------------------------
test: | $(VENV_DIR)/bin/activate  ## Execute unit & integration tests
	$(Q)$(VENV_BIN)/pytest --color=$(COLOR) -q $(SRC_DIRS)

coverage: | $(VENV_DIR)/bin/activate  ## Run tests with coverage reporting
	$(Q)$(VENV_BIN)/pytest --color=$(COLOR) --cov=$(APP_NAME) --cov-report=term-missing --cov-report=xml --cov-report=html

#-------------------------------------
# Database migrations (Alembic)
#-------------------------------------
migrate: | $(VENV_DIR)/bin/activate  ## Apply latest DB migrations
	$(Q)$(VENV_BIN)/alembic upgrade head

revision: | $(VENV_DIR)/bin/activate  ## Create new DB migration (requires -m "message")
ifndef m
	$(error Usage: make revision m="Add users table")
endif
	$(Q)$(VENV_BIN)/alembic revision --autogenerate -m "$(m)"

seed: | $(VENV_DIR)/bin/activate  ## Seed database with demo data
	$(Q)$(PYTHON) scripts/seed_data.py

#-------------------------------------
# Proto / gRPC code generation
#-------------------------------------
PROTO_DIR := proto
STUB_DIR  := $(APP_NAME)/generated

proto: | $(VENV_DIR)/bin/activate  ## Compile .proto files to Python stubs
	$(Q)echo "➤ Generating gRPC stubs…"
	$(Q)python -m grpc_tools.protoc -I=$(PROTO_DIR) --python_out=$(STUB_DIR) --grpc_python_out=$(STUB_DIR) $(shell find $(PROTO_DIR) -name '*.proto')

#-------------------------------------
# Application runtime
#-------------------------------------
run: | $(VENV_DIR)/bin/activate  ## Start API server locally using Uvicorn
	$(Q)$(VENV_BIN)/uvicorn $(APP_NAME).api.main:app --reload --host 0.0.0.0 --port 8000

#-------------------------------------
# Docker helpers
#-------------------------------------
docker-build: ## Build Docker image
	$(Q)docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

docker-push: ## Push Docker image to registry
	$(Q)docker push $(DOCKER_IMAGE):$(DOCKER_TAG)

docker-up: ## Start containers via docker-compose
	$(Q)docker compose -f $(COMPOSE_FILE) up -d

docker-down: ## Stop & remove containers
	$(Q)docker compose -f $(COMPOSE_FILE) down --remove-orphans

docker-logs: ## Tail application logs
	$(Q)docker compose -f $(COMPOSE_FILE) logs -f --tail=100

#-------------------------------------
# Git / pre-commit hooks
#-------------------------------------
hooks: | $(VENV_DIR)/bin/activate  ## Install git pre-commit hooks
	$(Q)$(VENV_BIN)/pre-commit install --install-hooks

#-------------------------------------
# CI convenience
#-------------------------------------
ci: lint coverage  ## Target executed in CI pipeline

#-------------------------------------
# Phony targets
#-------------------------------------
.PHONY: help setup clean lint format test coverage migrate revision seed proto run \
		docker-build docker-push docker-up docker-down docker-logs hooks ci

#-------------------------------------
# Self-documenting help
#-------------------------------------
help: ## Display this help screen
	$(Q)python - <<'PY' $(value PRINT_HELP_PYSCRIPT) < $(MAKEFILE_LIST)
PY
	$(Q)echo "" && echo "Variables (override with VAR=value):"
	$(Q)echo "  PYTHON_VERSION = $(PYTHON_VERSION)"
	$(Q)echo "  VERBOSE        = $(VERBOSE)"
	$(Q)echo "  COLOR          = $(COLOR)"
	$(Q)echo ""