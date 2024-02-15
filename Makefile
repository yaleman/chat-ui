.PHONY: docs

build_docs:
	poetry run python -m mkdocs build

docs:
	poetry run python -m mkdocs serve


run:
	poetry run chat-ui --reload