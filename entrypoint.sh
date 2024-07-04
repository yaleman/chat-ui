#!/bin/bash

opentelemetry-instrument \
    --logs_exporter console \
    uvicorn chat_ui:app --host "0.0.0.0" --port 9195 --forwarded-allow-ips '*'
