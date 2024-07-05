#!/bin/bash

if [ -z "${OTEL_RESOURCE_ATTRIBUTES}" ]; then
    echo "OTEL_RESOURCE_ATTRIBUTES env var needs to be set!"
    exit 1
fi
if [ -z "${CHATUI_APP_VERSION}" ]; then
    echo "CHATUI_APP_VERSION env var needs to be set!"
    exit 1
fi
if [ -z "${CHATUI_APP_VERSION}" ]; then
    echo "CHATUI_APP_VERSION env var needs to be set!"
    exit 1
fi
if [ -z "${SERVICE_NAME}" ]; then
    export SERVICE_NAME="chatui-llama"
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
# reset this from the root environment
export OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=""

export OTEL_RESOURCE_ATTRIBUTES="service.name=${SERVICE_NAME},service.namespace=${SERVICE_NAMESPACE},deployment.environment=${SERVICE_ENVIRONMENT},host.name=frontend"

poetry run opentelemetry-instrument \
		--logs_exporter console \
		python -m llama_cpp.server \
		--model "${MODEL_PATH}" \
		--chat_format "mistral-instruct" \
		--port 9196 \
		--n_gpu_layers -1 \
		--interrupt_requests False
