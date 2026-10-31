#!/bin/sh
set -eu
export WEB_LISTEN="${WEB_LISTEN:-0.0.0.0}" WEB_PORT="${WEB_PORT:-8080}" BRIDGE_PORT="${BRIDGE_PORT:-8098}" BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
# Configuration values are not allowed to introduce nginx directives.
case "$WEB_LISTEN" in *[!0-9.a-zA-Z:-]*|'') echo 'Invalid WEB_LISTEN' >&2; exit 1;; esac
case "$BRIDGE_HOST" in *[!0-9.a-zA-Z-]*|'') echo 'Invalid BRIDGE_HOST' >&2; exit 1;; esac
case "$WEB_PORT:$BRIDGE_PORT" in *[!0-9:]*|:*) echo 'Invalid ports' >&2; exit 1;; esac
BRIDGE_GATEWAY_TOKEN=$(cat /run/bridge/gateway-token)
export BRIDGE_GATEWAY_TOKEN
envsubst '${WEB_LISTEN} ${WEB_PORT} ${BRIDGE_PORT} ${BRIDGE_HOST} ${BRIDGE_GATEWAY_TOKEN}' < /etc/nginx/okam.conf.template > /tmp/nginx.conf
unset BRIDGE_GATEWAY_TOKEN
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
