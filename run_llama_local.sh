#!/bin/bash

# run_llama_local

export SERVICE_NAME="chatui-llama"

if [ -z "${SERVICE_NAMESPACE}" ]; then
	echo "Set the SERVICE_NAMESPACE environment variable"
	exit 1
fi
if [ -z "${SERVICE_ENVIRONMENT}" ]; then
	echo "Set the SERVICE_ENVIRONMENT environment variable"
	exit 1
fi

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
