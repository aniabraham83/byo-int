#!/bin/sh
set -eu

MOUNT_DIR="${TLS_MOUNT_DIR:-/certs}"
CERT_FILE="${TLS_CERT_FILE:-tls.crt}"
KEY_FILE="${TLS_KEY_FILE:-tls.key}"

TARGET_CERT="/etc/nginx/certs/localhost.crt"
TARGET_KEY="/etc/nginx/certs/localhost.key"

MOUNTED_CERT="${MOUNT_DIR}/${CERT_FILE}"
MOUNTED_KEY="${MOUNT_DIR}/${KEY_FILE}"

if [ -f "${MOUNTED_CERT}" ] && [ -f "${MOUNTED_KEY}" ]; then
    cp "${MOUNTED_CERT}" "${TARGET_CERT}"
    cp "${MOUNTED_KEY}" "${TARGET_KEY}"
    echo "Using mounted TLS certificate files from ${MOUNT_DIR}."
else
    echo "Mounted TLS certificate files not found; using bundled self-signed certificate."
fi

exec nginx -g "daemon off;"
