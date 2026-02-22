#!/usr/bin/env bash
set -euo pipefail

if [ -f /data/options.json ]; then
    export AUTOGEN_OPTIONS_PATH="/data/options.json"
fi

cd /app

exec uvicorn autogen.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level info \
    --forwarded-allow-ips="172.30.32.2"
