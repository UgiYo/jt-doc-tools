#!/bin/sh
set -eu

# Optional enterprise CA bundle injected at runtime.  Keep the private CA out of
# the externally-built image: mount it read-only inside the internal network and
# point JTDT_EXTRA_CA_CERTS at it.  Multiple files may be separated with ':'.
if [ -n "${JTDT_EXTRA_CA_CERTS:-}" ]; then
    system_bundle="/etc/ssl/certs/ca-certificates.crt"
    runtime_bundle="${JTDT_DATA_DIR:-/data}/.jtdt-ca-bundle.pem"
    tmp_bundle="${runtime_bundle}.tmp.$$"

    if [ ! -r "$system_bundle" ]; then
        echo "ERROR: system CA bundle is not readable: $system_bundle" >&2
        exit 1
    fi

    umask 077
    cp "$system_bundle" "$tmp_bundle"
    old_ifs=$IFS
    IFS=:
    for cert_file in $JTDT_EXTRA_CA_CERTS; do
        if [ ! -r "$cert_file" ]; then
            echo "ERROR: JTDT extra CA file is not readable: $cert_file" >&2
            rm -f "$tmp_bundle"
            exit 1
        fi
        if ! grep -q -- "-----BEGIN CERTIFICATE-----" "$cert_file"; then
            echo "ERROR: JTDT extra CA file is not a PEM certificate bundle: $cert_file" >&2
            rm -f "$tmp_bundle"
            exit 1
        fi
        printf '\n' >> "$tmp_bundle"
        cat "$cert_file" >> "$tmp_bundle"
    done
    IFS=$old_ifs
    mv "$tmp_bundle" "$runtime_bundle"

    export SSL_CERT_FILE="$runtime_bundle"
    export REQUESTS_CA_BUNDLE="$runtime_bundle"
    export CURL_CA_BUNDLE="$runtime_bundle"
    echo "JTDT: loaded additional CA certificate(s) from JTDT_EXTRA_CA_CERTS"
fi

exec "$@"
