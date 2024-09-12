#!/bin/bash

# Runs the Splunk OpenTelemetry collector in docker

set -e

# pinning the version to v0.103.0 because they changed the "localhost bind" behavior in v0.104.0
COLLECTOR_VERSION="0.103.0"

docker run --rm \
    -e "SPLUNK_ACCESS_TOKEN=${SPLUNK_ACCESS_TOKEN}" \
    -e "SPLUNK_REALM=${SPLUNK_REALM}" \
    -p 13133:13133 \
    -p 14250:14250 \
    -p 14268:14268 \
    -p 4317:4317 \
    -p 6060:6060 \
    -p 7276:7276 \
    -p 8888:8888 \
    -p 9080:9080 \
    -p 9411:9411 \
    -p 9943:9943 \
    --name otelcol "quay.io/signalfx/splunk-otel-collector:${COLLECTOR_VERSION}"
