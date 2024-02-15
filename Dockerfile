FROM python:3.12-slim

RUN mkdir /db/

WORKDIR /app

COPY pyproject.toml /app/
COPY README.md /app/
COPY ./chat_ui /app/chat_ui

RUN pip install --no-cache-dir --upgrade /app/

ENV CHATUI_DB_PATH=/db/chatui.sqlite3

CMD ["chat-ui"]