DEFAULT: help

.PHONY: help
help:
	@grep -E -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: build_docs
build_docs: ## Build the chat-ui docs
build_docs:
	poetry run python -m mkdocs build

.PHONY: serve_docs
serve_docs: ## Serve the chat-ui docs
serve_docs:
	poetry run python -m mkdocs serve

.PHONY: run
run: ## Run the chat-ui server in poetry
run:
	poetry run chat-ui --reload

.PHONY: docker/build
docker/build: ## Build the chat-ui docker container
docker/build:
	docker buildx build --load -t chat-ui .

.PHONY: docker
docker: ## Build and run the chat-ui docker container locally
docker: docker/build
	touch ~/.cache/chatui.sqlite3
	docker run --rm -it --init \
		--mount "type=bind,source=$(HOME)/.cache/chatui.sqlite3,target=/db/chatui.sqlite3" \
		--name chat-ui \
		-e "CHATUI_BACKEND_URL=$(CHATUI_BACKEND_URL)" \
		-p 9195:9195 chat-ui

.PHONY: llama/local
llama/local: ## Run the llama server locally
llama/local:
	poetry run python -m llama_cpp.server \
		--model "$(MODEL_PATH)" \
		--chat_format "mistral-instruct" \
		--port 9196 \
		--n_gpu_layers -1 \
		--interrupt_requests False

.PHONY: llama/docker
llama: ## Run the llama server in docker
llama:
	docker run --rm -it -p 9196:8000 \
		-d \
		--mount "type=bind,src=$(MODEL_PATH),target=/models/model.gguf" \
		-e MODEL=/models/model.gguf \
		--hostname llama \
		--name llama \
		ghcr.io/abetlen/llama-cpp-python:latest

.PHONY: checks
checks: ## Run linting etc
checks:
	poetry run mypy --strict tests chat_ui
	poetry run ruff tests chat_ui
	eslint chat_ui/js/*.js
	poetry run pytest