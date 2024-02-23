FROM python:3.12-slim

RUN adduser appuser --disabled-password
RUN mkdir /db/
RUN chown appuser:appuser /db/
RUN mkdir -p /home/appuser/.cache/ && chown -R appuser:appuser /home/appuser/.cache/
RUN mkdir -p /home/appuser/.config/ && chown -R appuser:appuser /home/appuser/.config/ && echo '{}' > /home/appuser/.config/chat-ui.json

WORKDIR /app
COPY pyproject.toml /app/
COPY README.md /app/
COPY ./chat_ui /app/chat_ui

USER appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"

RUN pip install --no-cache-dir /app/
ENV CHATUI_DB_PATH=/db/chatui.sqlite3


CMD ["chat-ui", "--host", "0.0.0.0"]