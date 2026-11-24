#!/bin/sh
# Create a private CA and a broker certificate for the LAN TLS listener (port 8883).
# Runs inside a throwaway container (see `just tls-cert`):
#   /tls  = Docker volume mounted by the broker (keys stay here, never in the repo)
#   /out  = repo folder that receives only the public CA certificate for the ESP32
# Usage: make-lan-cert.sh <broker IP> [more IPs/hostnames...]
# Existing CA is reused so devices that already have mqtt_ca.pem keep working.
set -eu

[ "$#" -ge 1 ] || { echo "usage: $0 <broker-ip> [names...]" >&2; exit 2; }
apk add -q openssl >/dev/null

cd /tls
# The ESP32 may connect before NTP sync (clock at 2000-01-01): start validity in 2000.
NOT_BEFORE=20000101000000Z
NOT_AFTER=20361231235959Z

if [ ! -f ca.key ] || [ ! -f ca.crt ]; then
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
        -keyout ca.key -out ca.crt -subj "/CN=IoT Smart Barn LAN CA" \
        -not_before "$NOT_BEFORE" -not_after "$NOT_AFTER" \
        -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
    echo "created CA"
fi

san="IP:127.0.0.1,DNS:localhost,DNS:mosquitto"
for name in "$@"; do
    case "$name" in
        *[!0-9.]*) san="$san,DNS:$name" ;;
        *) san="$san,IP:$name" ;;
    esac
done

openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout privkey.pem -out server.csr -subj "/CN=$1"
printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' "$san" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -not_before "$NOT_BEFORE" -not_after "$NOT_AFTER" -extfile server.ext -out server.crt
cat server.crt ca.crt > fullchain.pem
rm -f server.csr server.ext
chown 1883:1883 privkey.pem ca.key
chmod 640 privkey.pem
chmod 600 ca.key

cp ca.crt /out/mqtt_ca.pem
echo "broker certificate for: $san"
openssl x509 -in server.crt -noout -subject -dates
