#!/usr/bin/with-contenv bashio
# ==============================================================================
# Reads add-on options, exports them as env vars the app understands, and
# starts the FastAPI app. Kept intentionally thin: all real logic lives in
# app/, so it's testable without a Supervisor around it.
# ==============================================================================
set -e

bashio::log.info "Starting Traffic Monitor..."

export TM_API_KEY
export TM_UNIT_SYSTEM
export TM_LOG_LEVEL
export TM_INGRESS_PORT="8099"

TM_API_KEY=$(bashio::config 'api_key')
TM_UNIT_SYSTEM=$(bashio::config 'unit_system')
TM_LOG_LEVEL=$(bashio::config 'log_level')

if bashio::services.available "mqtt"; then
    bashio::log.info "MQTT service found via Supervisor, fetching credentials..."
    export TM_MQTT_HOST
    export TM_MQTT_PORT
    export TM_MQTT_USERNAME
    export TM_MQTT_PASSWORD
    TM_MQTT_HOST=$(bashio::services mqtt "host")
    TM_MQTT_PORT=$(bashio::services mqtt "port")
    TM_MQTT_USERNAME=$(bashio::services mqtt "username")
    TM_MQTT_PASSWORD=$(bashio::services mqtt "password")
else
    bashio::log.warning "No MQTT service found. Entities will not be published until MQTT is configured."
fi

if bashio::config.is_empty 'api_key'; then
    bashio::log.warning "No TomTom API key configured yet. Set one in the add-on Configuration tab."
fi

# uvicorn only understands critical/error/warning/info/debug/trace; the HA
# log_level schema also allows notice/fatal, so map those down.
UVICORN_LOG_LEVEL="${TM_LOG_LEVEL:-info}"
case "${UVICORN_LOG_LEVEL}" in
    notice) UVICORN_LOG_LEVEL="info" ;;
    fatal) UVICORN_LOG_LEVEL="critical" ;;
esac

cd /app
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${TM_INGRESS_PORT}" --log-level "${UVICORN_LOG_LEVEL}"
