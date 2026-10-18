#!/bin/bash
# Starts the bridge behind nginx: nginx sends the big files (videos, APK) itself,
# Python handles the API. If nginx is missing, disabled (NGINX_ENABLED=false) or
# fails its self-check, the Python server alone serves everything, as before.
set -u

PORT="${PORT:-8090}"
APP_PORT="${APP_PORT:-8091}"
MEDIA="${MEDIA_DIR:-/app/media}"
CONF_DIR=/tmp/nginx

log() { echo "[start] $*"; }

direct() {
    log "mode direct : Python sert tout sur le port $PORT ($1)"
    unset NGINX_ACCEL
    exec python -m bridge
}

if [ "${NGINX_ENABLED:-true}" != "true" ]; then direct "NGINX_ENABLED=false"; fi
if ! command -v nginx >/dev/null 2>&1; then direct "nginx absent"; fi

mkdir -p "$MEDIA" "$CONF_DIR"
sed -e "s|__PORT__|$PORT|g" -e "s|__APP_PORT__|$APP_PORT|g" -e "s|__MEDIA_DIR__|$MEDIA|g" \
    /app/docker/nginx.conf.template > "$CONF_DIR/nginx.conf"
if ! nginx -t -q -c "$CONF_DIR/nginx.conf"; then direct "configuration nginx invalide"; fi

# 1. Python on an internal port
HOST=127.0.0.1 PORT="$APP_PORT" PUBLIC_PORT="$PORT" NGINX_ACCEL=1 python -m bridge &
APP_PID=$!
ready=0
for _ in $(seq 1 120); do
    if ! kill -0 "$APP_PID" 2>/dev/null; then log "Python s'est arrêté au démarrage"; exit 1; fi
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$APP_PORT/health', timeout=2)" 2>/dev/null; then
        ready=1; break
    fi
    sleep 1
done
if [ "$ready" != 1 ]; then
    kill "$APP_PID" 2>/dev/null; wait "$APP_PID" 2>/dev/null
    direct "Python ne répond pas sur le port interne"
fi

# 2. nginx on the public port
nginx -c "$CONF_DIR/nginx.conf" -g "daemon off;" &
NGINX_PID=$!

# 3. Self-check: a file sent by nginx on behalf of Python must come back intact
TOKEN="accel-$(date +%s%N)"
printf '%s' "$TOKEN" > "$MEDIA/.accel-check"
if python - "$PORT" "$TOKEN" <<'EOF'
import sys, time, urllib.request
port, token = sys.argv[1], sys.argv[2]
for _ in range(15):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/accel", timeout=3) as r:
            sys.exit(0 if r.read().decode() == token else 1)
    except Exception:
        time.sleep(1)
sys.exit(1)
EOF
then
    log "nginx actif : vidéos et APK envoyés par nginx, API par Python (port interne $APP_PORT)"
else
    log "auto-test nginx échoué"
    kill "$NGINX_PID" "$APP_PID" 2>/dev/null
    wait 2>/dev/null
    direct "repli automatique"
fi

# Stop both when the container stops or when one of them exits
trap 'kill -TERM "$NGINX_PID" "$APP_PID" 2>/dev/null' TERM INT
wait -n "$APP_PID" "$NGINX_PID"
code=$?
log "un processus s'est arrêté (code $code) : arrêt du conteneur"
kill -TERM "$NGINX_PID" "$APP_PID" 2>/dev/null
wait
exit "$code"
