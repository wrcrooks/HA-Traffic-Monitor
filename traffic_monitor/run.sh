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
export TM_ROUTE_NAME
export TM_ROUTE_AVOID_TOLLS
export TM_ROUTE_POLL_INTERVAL_MINUTES

TM_API_KEY=$(bashio::config 'api_key')
TM_UNIT_SYSTEM=$(bashio::config 'unit_system')
TM_LOG_LEVEL=$(bashio::config 'log_level')
TM_ROUTE_NAME=$(bashio::config 'route_name')
TM_ROUTE_AVOID_TOLLS=$(bashio::config 'route_avoid_tolls')
TM_ROUTE_POLL_INTERVAL_MINUTES=$(bashio::config 'route_poll_interval_minutes')

# route_origin/route_destination are truly optional (no default in
# options -- see config.yaml) and only used once, as a one-time seed for
# the legacy M2 config. Guard with is_empty before fetching, the same
# pattern used for mqtt_host below: calling bashio::config directly on an
# unset optional key isn't something to rely on under `set -e`.
export TM_ROUTE_ORIGIN=""
export TM_ROUTE_DESTINATION=""
if ! bashio::config.is_empty 'route_origin'; then
    TM_ROUTE_ORIGIN=$(bashio::config 'route_origin')
fi
if ! bashio::config.is_empty 'route_destination'; then
    TM_ROUTE_DESTINATION=$(bashio::config 'route_destination')
fi

# MQTT: auto-discover via the Supervisor's mqtt:want service, but let a
# manually-configured host in the add-on options override it (e.g. for a
# broker outside the Supervisor's knowledge).
export TM_MQTT_HOST=""
export TM_MQTT_PORT=""
export TM_MQTT_USERNAME=""
export TM_MQTT_PASSWORD=""

if bashio::services.available "mqtt"; then
    bashio::log.info "MQTT service found via Supervisor, fetching credentials..."
    TM_MQTT_HOST=$(bashio::services mqtt "host")
    TM_MQTT_PORT=$(bashio::services mqtt "port")
    TM_MQTT_USERNAME=$(bashio::services mqtt "username")
    TM_MQTT_PASSWORD=$(bashio::services mqtt "password")
else
    bashio::log.warning "No MQTT service found via Supervisor. Configure mqtt_host manually, or install/set up an MQTT broker."
fi

if ! bashio::config.is_empty 'mqtt_host'; then
    bashio::log.info "Using manually configured MQTT host, overriding Supervisor discovery."
    TM_MQTT_HOST=$(bashio::config 'mqtt_host')
    TM_MQTT_PORT=$(bashio::config 'mqtt_port')
    TM_MQTT_USERNAME=$(bashio::config 'mqtt_username')
    TM_MQTT_PASSWORD=$(bashio::config 'mqtt_password')
fi

if bashio::config.is_empty 'api_key'; then
    bashio::log.warning "No TomTom API key configured yet. Set one in the add-on Configuration tab."
fi

if bashio::config.is_empty 'route_origin' || bashio::config.is_empty 'route_destination'; then
    bashio::log.info "No legacy route_origin/route_destination set -- manage routes via the add-on's API/UI instead."
fi

# uvicorn only understands critical/error/warning/info/debug/trace; the HA
# log_level schema also allows notice/fatal, so map those down.
export TM_UVICORN_LOG_LEVEL="${TM_LOG_LEVEL:-info}"
case "${TM_UVICORN_LOG_LEVEL}" in
    notice) TM_UVICORN_LOG_LEVEL="info" ;;
    fatal) TM_UVICORN_LOG_LEVEL="critical" ;;
esac

cd /app
# `python3 -m app`, not `python3 -m uvicorn app.main:app` -- see
# app/__main__.py for why the difference matters.
exec python3 -m app
