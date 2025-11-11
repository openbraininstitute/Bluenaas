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
ifeq ($(CI),true)
  UID := 1000
  GID := 1000
else
  UID := $(shell id -u)
  GID := $(shell id -g)
endif

export UID
export GID

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-23s\033[0m %s\n", $$1, $$2}'

init-repo-config: ## Initialize repo config to enable fetching private packages
	@if [ -n "$$SSH_AUTH_SOCK" ]; then \
		echo "Using SSH_AUTH_SOCK" \
		git config url."ssh://git@github.com/".insteadOf "https://github.com/"; \
	elif [ -n "$$GH_PRIVATE_REPO_TOKEN" ]; then \
		echo "Using GH_PRIVATE_REPO_TOKEN" \
		git config url."https://$$GH_PRIVATE_REPO_TOKEN@github.com/".insteadOf "https://github.com/"; \
	else \
		echo "Warning: neither of GH_PRIVATE_REPO_TOKEN or SSH_AUTH_SOCK is provided"; \
	fi

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
	uv run python -m unittest discover

check-all: format-check type-check job-fn-reference-check test ## Run all checkers

PROGRESS_FLAG := $(if $(CI),--progress=plain,)

build:  ## Build the Docker images
	docker compose $(PROGRESS_FLAG) build api
	@if [ -n "$$SSH_AUTH_SOCK" ]; then \
		docker compose $(PROGRESS_FLAG) build --ssh github_ssh=$$SSH_AUTH_SOCK worker; \
	else \
		docker compose $(PROGRESS_FLAG) build worker; \
	fi

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
