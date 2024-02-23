.PHONY: docs

build_docs:
	poetry run python -m mkdocs build

docs:
	poetry run python -m mkdocs serve

run:
	poetry run chat-ui --reload

docker/build:
	docker build -t chat-ui .

docker: docker/build
	docker run --rm -it --init -d --name chat-ui -e "CHATUI_BACKEND_URL=$(CHATUI_BACKEND_URL)" -p 9195:9195 chat-ui

llama:
	docker run --rm -it -p 9196:8000 \
		-d \
		--mount "type=bind,src=$(MODEL_PATH),target=/models/model.gguf" \
		-e MODEL=/models/model.gguf \
		--hostname llama \
		--name llama \
		ghcr.io/abetlen/llama-cpp-python:latest
