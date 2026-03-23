#!/bin/sh
set -eu
: "${SDR_API_BASE_URL:=/runtime-api}"
: "${SDR_API_TOKEN:=}"
: "${SDR_RUNTIME_UPSTREAM:=sdr-runtime:8081}"
: "${UI_BIND:=0.0.0.0}"
: "${UI_PORT:=3001}"
envsubst '${SDR_API_BASE_URL} ${SDR_API_TOKEN} ${SDR_RUNTIME_UPSTREAM} ${UI_BIND} ${UI_PORT}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf
envsubst '${SDR_API_BASE_URL} ${SDR_API_TOKEN} ${SDR_RUNTIME_UPSTREAM} ${UI_BIND} ${UI_PORT}' \
  < /usr/share/nginx/html/config.template.js \
  > /usr/share/nginx/html/config.js
exec nginx -g 'daemon off;'
