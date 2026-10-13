SHELL := /bin/bash

export ENVIRONMENT ?= dev
export APP_NAME := single-cell-simulator
# export APP_VERSION := $(shell git describe --abbrev --dirty --always --tags)
# export COMMIT_SHA := $(shell git rev-parse HEAD)
export IMAGE_NAME ?= $(APP_NAME)
export IMAGE_TAG_SUFFIX ?= staging
# export IMAGE_TAG_ALIAS := latest
# ifneq ($(ENVIRONMENT), prod)
# 	export IMAGE_TAG := $(IMAGE_TAG)-$(ENVIRONMENT)
# 	export IMAGE_TAG_ALIAS := $(IMAGE_TAG_ALIAS)-$(ENVIRONMENT)
# endif

# This ensures that owner uid/gid for the volume mounts match the host user.
UID := $(shell id -u)
GID := $(shell id -g)

export UID
export GID

# AWS CodeArtifact repository hosting the private packages
CODEARTIFACT_DOMAIN := openbraininstitute
CODEARTIFACT_DOMAIN_OWNER := 985539765147
CODEARTIFACT_REGION := us-east-1

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-23s\033[0m %s\n", $$1, $$2}'

codeartifact-env:  ## Print exports for fetching private packages, use as: eval "$(make -s codeartifact-env)"
	@token=$$(aws codeartifact get-authorization-token \
		--domain $(CODEARTIFACT_DOMAIN) \
		--domain-owner $(CODEARTIFACT_DOMAIN_OWNER) \
		--region $(CODEARTIFACT_REGION) \
		--query authorizationToken \
		--output text) \
		&& echo "export CODEARTIFACT_TOKEN=$$token" \
		&& echo "export UV_INDEX_CODEARTIFACT_USERNAME=aws" \
		&& echo "export UV_INDEX_CODEARTIFACT_PASSWORD=$$token"

install:  ## Install dependencies into .venv
	uv sync --no-install-project --all-groups

compile-deps:  ## Create or update the lock file, without upgrading the version of the dependencies
	uv lock

upgrade-deps:  ## Create or update the lock file, using the latest version of the dependencies
	uv lock --upgrade

check-deps:  ## Check that the dependencies in the existing lock file are valid
	uv lock --locked

format:  ## Run formatters
	uv run -m ruff format

format-check:  ## Run formatters and check that the code is formatted correctly
	uv run -m ruff check

type-check: ## Run type checkers
	uv run pyright app

job-fn-reference-check:  ## Validate JobFn enum references
	uv run python scripts/validate_job_fn_refs.py

test:  ## Run unit tests
	@# -W flag suppresses "coroutine was never awaited" RuntimeWarnings emitted by
	@# CPython's coroutine GC finalizer when mocked async dispatch returns unawaited
	@# coroutines during test teardown. Python-level warnings.filterwarnings cannot
	@# catch these because they are emitted at the C level.
	LOG_LEVEL=WARNING LOG_LEVEL_LIBS=WARNING uv run python -W "ignore::RuntimeWarning" -m unittest discover

check-all: format-check type-check job-fn-reference-check test ## Run all checkers

PROGRESS_FLAG := $(if $(CI),--progress=plain,)

build:  ## Build the Docker images
	docker compose $(PROGRESS_FLAG) build api worker

publish: build  ## Publish the Docker images to DockerHub
	docker compose push api
	docker compose push worker

run: build  ## Run the application in Docker
	docker compose up --watch --remove-orphans

job-monitor: ## Run the RQ job/queue monitor
	docker compose run --rm \
		--entrypoint sh \
		worker -c "rq info --url redis://redis:6379 --interval 1"

kill:  ## Take down the application containers and remove the volumes
	docker compose down --remove-orphans --volumes
