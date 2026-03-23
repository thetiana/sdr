#!/bin/sh
set -eu
: "${SDR_API_BASE_URL:=http://sdr-runtime:8080}"
: "${SDR_API_TOKEN:=}"
: "${UI_BIND:=0.0.0.0}"
: "${UI_PORT:=3000}"
envsubst '${SDR_API_BASE_URL} ${SDR_API_TOKEN} ${UI_BIND} ${UI_PORT}' \
  < /usr/share/nginx/html/config.template.js \
  > /usr/share/nginx/html/config.js
exec nginx -g 'daemon off;'
