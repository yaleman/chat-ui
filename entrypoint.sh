#!/bin/bash

if [ -z "${OTEL_RESOURCE_ATTRIBUTES}" ]; then
    echo "OTEL_RESOURCE_ATTRIBUTES env var needs to be set!"
    exit 1
fi
if [ -z "${CHATUI_APP_VERSION}" ]; then
    echo "CHATUI_APP_VERSION env var needs to be set!"
    exit 1
fi
if [ -z "${SERVICE_NAME}" ]; then
    echo "SERVICE_NAME env var needs to be set!"
    exit 1
fi
if [ -z "${SERVICE_NAMESPACE}" ]; then
    echo "SERVICE_NAMESPACE env var needs to be set!"
    exit 1
fi
if [ -z "${SERVICE_ENVIRONMENT}" ]; then
    echo "SERVICE_ENVIRONMENT env var needs to be set!"
    exit 1
fi
echo "All env var checks passed!"

OTEL_SERVICE_NAME="${SERVICE_NAME}"
export OTEL_SERVICE_NAME

opentelemetry-instrument \
    uvicorn chat_ui:app --host "0.0.0.0" --port 9195 --forwarded-allow-ips '*'
