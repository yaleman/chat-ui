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
	docker run --rm -it --init --name chat-ui -p 9195:9195 chat-ui