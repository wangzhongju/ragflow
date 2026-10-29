#!/bin/sh
# Run as root inside this project's Elasticsearch container.
set -eu
chown 1000:0 /snapshots
# Generated passwords are hexadecimal, so they can be embedded in JSON safely.
case "$KIBANA_PASSWORD" in ''|*[!a-fA-F0-9]*) echo 'KIBANA_PASSWORD must be hexadecimal' >&2; exit 2 ;; esac
curl -fsS --max-time 30 -u "elastic:$ELASTIC_PASSWORD" \
  -H 'Content-Type: application/json' -X POST \
  http://127.0.0.1:9200/_security/user/kibana_system/_password \
  --data-binary "{\"password\":\"$KIBANA_PASSWORD\"}"
curl -fsS --max-time 30 -u "elastic:$ELASTIC_PASSWORD" \
  -H 'Content-Type: application/json' -X PUT \
  http://127.0.0.1:9200/_snapshot/ragflow_backup \
  --data-binary '{"type":"fs","settings":{"location":"/snapshots","compress":true}}'
printf '\nStorage administration configured.\n'
