FROM python:3.12-slim


# install curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* && rm -rf /var/cache/apt/
RUN adduser appuser --disabled-password
RUN mkdir /db/
RUN chown appuser:appuser /db/
RUN mkdir -p /home/appuser/.cache/ && chown -R appuser:appuser /home/appuser/.cache/
RUN mkdir -p /home/appuser/.config/ && chown -R appuser:appuser /home/appuser/.config/ && echo '{}' > /home/appuser/.config/chat-ui.json

WORKDIR /app
COPY pyproject.toml /app/
COPY README.md /app/
COPY ./chat_ui /app/chat_ui
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
USER appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"

RUN pip install --no-cache-dir --user /app/

RUN opentelemetry-bootstrap --action=install

ENV CHATUI_DB_PATH=/db/chatui.sqlite3

HEALTHCHECK --interval=15s --timeout=3s \
  CMD /usr/bin/curl -sf http://localhost:9195/healthcheck || exit 1

# CMD ["python", "-m", "chat_ui", "--host", "0.0.0.0"]
CMD [ "/entrypoint.sh" ]