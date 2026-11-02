#!/bin/sh
# Start Mosquitto, creating the Dynamic Security file on first run and
# (re)applying the roles from docs/protocol.md section 8 on every start.
set -eu

: "${MQTT_BACKEND_PASSWORD:?set MQTT_BACKEND_PASSWORD in deployment/.env}"
: "${MQTT_BOOTSTRAP_PASSWORD:?set MQTT_BOOTSTRAP_PASSWORD in deployment/.env}"

DYNSEC=/mosquitto/data/dynamic-security.json
if [ ! -f "$DYNSEC" ]; then
    echo "init: creating $DYNSEC with admin client 'backend'"
    mosquitto_ctrl dynsec init "$DYNSEC" backend "$MQTT_BACKEND_PASSWORD" >/dev/null
fi
chown -R mosquitto:mosquitto /mosquitto/data
rm -f /tmp/dynsec-ready

mosquitto -c /mosquitto/config/mosquitto.conf &
BROKER_PID=$!
trap 'kill -TERM "$BROKER_PID" 2>/dev/null' TERM INT

ctrl() {
    # Existing roles/clients/ACLs report an error; that is expected on restarts.
    mosquitto_ctrl -h 127.0.0.1 -u backend -P "$MQTT_BACKEND_PASSWORD" dynsec "$@" >/dev/null 2>&1 || true
}

for _ in $(seq 1 50); do
    if mosquitto_ctrl -h 127.0.0.1 -u backend -P "$MQTT_BACKEND_PASSWORD" dynsec getDefaultACLAccess >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

ctrl createRole backend
ctrl addRoleACL backend publishClientSend 'iot/v1/#' allow
ctrl addClientRole backend backend

# Mosquitto 2.0 dynsec does not expand %c/%u in ACLs, so bootstrap gets the
# whole provision branch (responses carry no secrets) and each device gets
# its own literal role, created by the backend on approval.
ctrl createRole bootstrap
ctrl addRoleACL bootstrap publishClientSend 'iot/v1/provision/+/request' allow
ctrl addRoleACL bootstrap subscribePattern 'iot/v1/provision/+/response' allow
ctrl createClient bootstrap -p "$MQTT_BOOTSTRAP_PASSWORD"
ctrl setClientPassword bootstrap "$MQTT_BOOTSTRAP_PASSWORD"
ctrl addClientRole bootstrap bootstrap
ctrl deleteRole device

touch /tmp/dynsec-ready
echo "init: dynamic security roles ready"
wait "$BROKER_PID"
