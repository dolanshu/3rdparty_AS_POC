#!/usr/bin/env bash
# Phase 3 demo stack — one terminal, four processes.
# Usage: ./scripts/phase3-demo.sh [simple|full]
#   simple = translation AS only (3 processes + core mock)
#   full   = anti-fraud AS -> translation AS -> core (5 processes + mock)
# Ctrl+C kills everything cleanly.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-simple}"
LOG_DIR="/tmp/p3-demo"
mkdir -p "$LOG_DIR"

# Allocate ports (override with env vars if needed)
CORE_SIP="${CORE_SIP:-5061}"
CORE_UAC="${CORE_UAC:-5062}"       # mock UAC side — MUST differ from AS_TRANS_SIP below
AS_TRANS_SIP="${AS_TRANS_SIP:-5060}"
AS_TRANS_API="${AS_TRANS_API:-8080}"
AS_FRAUD_SIP="${AS_FRAUD_SIP:-5063}"
AS_FRAUD_API="${AS_FRAUD_API:-8082}"
GEN_HTTP="${GEN_HTTP:-8765}"
CONSOLE_HTTP="${CONSOLE_HTTP:-8081}"

PIDS=()

cleanup() {
  echo ""
  echo "--- shutting down ---"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "--- done ---"
  exit 0
}
trap cleanup INT TERM

wait_port() {
  local port="$1" host="${2:-127.0.0.1}"
  local deadline=$(( SECONDS + 10 ))
  while (( SECONDS < deadline )); do
    ss -tlnp 2>/dev/null | grep -q ":$port " && return 0
    ss -ulnp 2>/dev/null | grep -q ":$port " && return 0
    sleep 0.3
  done
  return 1
}

echo "==> Phase 3 demo stack — $MODE mode"
echo "    logs: $LOG_DIR/"

# --- Rewrite routing_rules.yaml next_hop ports to point at core mock ---
# The shipped config has s-sbc-primary..intl-gateway ports 15061-15066, but
# the core mock only listens on CORE_SIP. conftest.py does this rewrite for
# pytest; demo script must do it too.
RULES_FILE="config/routing_rules.yaml"
if [[ -f "$RULES_FILE" ]]; then
  echo "[rewrite] routing_rules.yaml next_hop ports -> $CORE_SIP"
  uv run python -c "
import yaml, pathlib
p = pathlib.Path('$RULES_FILE')
d = yaml.safe_load(p.read_text())
for nh in d.get('next_hops', []):
    nh['port'] = $CORE_SIP
tmp = p.with_suffix('.yaml.bak')
if not tmp.exists(): p.rename(tmp)
p.write_text(yaml.safe_dump(d, sort_keys=False))
"
else
  echo "[warn] $RULES_FILE not found — AS may route nowhere"
fi

# --- core mock (UAS side on UDP) ---
# NOTE: mock has TWO SIP endpoints — UAS (listen-port, defaults to 15061)
# and UAC (trunk-port, defaults to listen-port minus one). We MUST pin
# --trunk-port explicitly because --listen-port 5061 would make trunk-port
# default to 5060, which collides with the translation AS's SIP listen port.
echo "[0/4] core mock :$CORE_SIP (UAS) trunk :$CORE_UAC (UAC)"
uv run python -m s_sbc_mock.main \
  --listen-port "$CORE_SIP" \
  --trunk-port "$CORE_UAC" \
  > "$LOG_DIR/core.log" 2>&1 &
PIDS+=($!)

if [[ "$MODE" == "full" ]]; then
  # --- anti-fraud AS (AS-1) ---
  echo "[1/4] anti-fraud AS :$AS_FRAUD_SIP API :$AS_FRAUD_API"
  FRAUD_SIP_LISTEN_PORT="$AS_FRAUD_SIP" \
  FRAUD_INTERNAL_API_PORT="$AS_FRAUD_API" \
  FRAUD_SBC_PEER_ADDRESS=127.0.0.1 \
  FRAUD_SBC_PEER_PORT="$AS_TRANS_SIP" \
  FRAUD_ALLOWED_PEERS=127.0.0.1 \
    uv run python -m anti_fraud_as.main \
    > "$LOG_DIR/fraud.log" 2>&1 &
  PIDS+=($!)
fi

# --- translation AS (AS-2 in full mode, the only AS in simple) ---
echo "[2/4] translation AS :$AS_TRANS_SIP API :$AS_TRANS_API"
SBC_PEER_ADDRESS=127.0.0.1 \
SBC_PEER_PORT="$CORE_SIP" \
SIP_LISTEN_PORT="$AS_TRANS_SIP" \
INTERNAL_API_PORT="$AS_TRANS_API" \
  uv run python -m as_app.main \
  > "$LOG_DIR/trans.log" 2>&1 &
PIDS+=($!)

# --- load generator ---
GEN_AS_PORT="$AS_FRAUD_SIP"
[[ "$MODE" == "simple" ]] && GEN_AS_PORT="$AS_TRANS_SIP"
echo "[3/4] load generator -> AS :$GEN_AS_PORT HTTP :$GEN_HTTP"
uv run python tools/call_load_generator.py \
  --as-port "$GEN_AS_PORT" \
  --http-port "$GEN_HTTP" \
  > "$LOG_DIR/gen.log" 2>&1 &
PIDS+=($!)

# --- enhanced console ---
echo "[4/4] console :$CONSOLE_HTTP -> AS API :$AS_TRANS_API / load API :$GEN_HTTP"
uv run python -m console.main \
  --port "$CONSOLE_HTTP" \
  --as-api-url "http://127.0.0.1:$AS_TRANS_API" \
  --load-api-url "http://127.0.0.1:$GEN_HTTP" \
  > "$LOG_DIR/console.log" 2>&1 &
PIDS+=($!)

echo ""
echo "    waiting for ports to bind..."
for port in "$CORE_SIP" "$AS_TRANS_API" "$GEN_HTTP" "$CONSOLE_HTTP"; do
  if wait_port "$port"; then
    echo "      :$port  OK"
  else
    echo "      :$port  TIMEOUT — check $LOG_DIR/"
  fi
done

echo ""
echo "==> stack ready"
echo "    console:  http://127.0.0.1:$CONSOLE_HTTP"
echo "    healthz:  curl -s http://127.0.0.1:$AS_TRANS_API/healthz"
echo "    generator: curl -X POST http://127.0.0.1:$GEN_HTTP/load/start"
echo "    console -> Load Generator -> Start"
echo ""
echo "    ctrl+c to stop everything"

wait
