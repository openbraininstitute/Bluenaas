SHELL := /bin/bash

export ENVIRONMENT ?= dev
export APP_NAME := single-cell-simulator
# export APP_VERSION := $(shell git describe --abbrev --dirty --always --tags)
# export COMMIT_SHA := $(shell git rev-parse HEAD)
export IMAGE_NAME ?= $(APP_NAME)
export IMAGE_TAG_SUFFIX := staging
# export IMAGE_TAG_ALIAS := latest
# ifneq ($(ENVIRONMENT), prod)
# 	export IMAGE_TAG := $(IMAGE_TAG)-$(ENVIRONMENT)
# 	export IMAGE_TAG_ALIAS := $(IMAGE_TAG_ALIAS)-$(ENVIRONMENT)
# endif

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-23s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies into .venv
	uv sync --no-install-project

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
	poetry run pyright bluenaas

PROGRESS_FLAG := $(if $(CI),--progress=plain,)

build:  ## Build the Docker images
	docker compose $(PROGRESS_FLAG) build api
	docker compose $(PROGRESS_FLAG) build worker

publish: build  ## Publish the Docker images to DockerHub
	docker compose push api
	docker compose push worker

run: build  ## Run the application in Docker
	docker compose up --watch --remove-orphans

kill:  ## Take down the application containers and remove the volumes
	docker compose down --remove-orphans --volumes

generate-entitycore-schemas: ## Generate entitycore schemas
	curl -o openapi.json https://staging.openbraininstitute.org/api/entitycore/openapi.json \
	&& uv run datamodel-codegen --input openapi.json --input-file-type openapi --output _schemas.py