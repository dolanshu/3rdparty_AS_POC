#!/usr/bin/env bash
# Phase 3 demo stack — one terminal, multiple processes.
# Usage: ./scripts/phase3-demo.sh [simple|full]
#   simple = translation AS only + core mock (topology simple)
#   full   = P9b iFC chain: fraud AS -> translation AS via ims_mock runtime (topology chained)
# Ctrl+C kills everything cleanly.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-simple}"
LOG_DIR="/tmp/p3-demo"
mkdir -p "$LOG_DIR"

# WSL2: services bind 127.0.0.1 only → Windows browser gets ERR_EMPTY_RESPONSE on
# http://127.0.0.1:8081. Bind 0.0.0.0 and open console via the WSL IP from Windows.
if grep -qi microsoft /proc/version 2>/dev/null; then
  WSL_IP="$(hostname -I | awk '{print $1}')"
  BIND_ADDR="${BIND_ADDR:-0.0.0.0}"
  API_HOST="${API_HOST:-$WSL_IP}"
else
  WSL_IP=""
  BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
  API_HOST="${API_HOST:-127.0.0.1}"
fi

NO_PROXY_LIST="127.0.0.1,localhost,::1"
[[ -n "$WSL_IP" ]] && NO_PROXY_LIST="$NO_PROXY_LIST,$WSL_IP"
export NO_PROXY="$NO_PROXY_LIST"
export no_proxy="$NO_PROXY"

# Allocate ports (override with env vars if needed)
CORE_SIP="${CORE_SIP:-5061}"
CORE_UAC="${CORE_UAC:-5062}"
AS_TRANS_SIP="${AS_TRANS_SIP:-5060}"
AS_TRANS_API="${AS_TRANS_API:-8080}"
AS_FRAUD_SIP="${AS_FRAUD_SIP:-5063}"
AS_FRAUD_API="${AS_FRAUD_API:-8082}"
IMS_RETURN="${IMS_RETURN:-5070}"
IMS_FORWARD="${IMS_FORWARD:-5071}"
IMS_TERM="${IMS_TERM:-5072}"
IMS_PCSCF="${IMS_PCSCF:-5073}"
GEN_HTTP="${GEN_HTTP:-8765}"
CONSOLE_HTTP="${CONSOLE_HTTP:-8081}"
GEN_SIP="${GEN_SIP:-5099}"

PIDS=()

cleanup() {
  echo ""
  echo "--- shutting down ---"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  [[ -f config/routing_rules.yaml.bak ]] && mv -f config/routing_rules.yaml.bak config/routing_rules.yaml
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

free_ports() {
  local port
  for port in "$CORE_SIP" "$CORE_UAC" "$AS_TRANS_SIP" "$AS_TRANS_API" \
              "$AS_FRAUD_SIP" "$AS_FRAUD_API" "$IMS_RETURN" "$IMS_FORWARD" \
              "$IMS_TERM" "$IMS_PCSCF" "$GEN_HTTP" "$CONSOLE_HTTP" "$GEN_SIP"; do
    if command -v lsof >/dev/null 2>&1; then
      lsof -ti ":$port" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    fi
  done
  sleep 0.5
}

rewrite_rules_to_port() {
  local target_port="$1"
  local rules_file="config/routing_rules.yaml"
  if [[ ! -f "$rules_file" ]]; then
    echo "[warn] $rules_file not found — AS may route nowhere"
    return
  fi
  echo "[rewrite] routing_rules.yaml next_hop ports -> $target_port"
  uv run python -c "
import yaml, pathlib
p = pathlib.Path('$rules_file')
d = yaml.safe_load(p.read_text())
for nh in d.get('next_hops', []):
    nh['port'] = $target_port
tmp = p.with_suffix('.yaml.bak')
if not tmp.exists(): p.rename(tmp)
p.write_text(yaml.safe_dump(d, sort_keys=False))
"
}

echo "==> Phase 3 demo stack — $MODE mode (P14 topology)"
echo "    logs: $LOG_DIR/"
echo "    bind: $BIND_ADDR  api-host: $API_HOST"
[[ -n "$WSL_IP" ]] && echo "    wsl:  open http://$WSL_IP:$CONSOLE_HTTP from Windows browser"

echo "[preflight] freeing demo ports..."
free_ports

GEN_TOPOLOGY="simple"
GEN_INGRESS="$AS_TRANS_SIP"
GEN_ROUTE_RETURN_ARGS=()
FRAUD_API_ARG=()

if [[ "$MODE" == "full" ]]; then
  GEN_TOPOLOGY="chained"
  GEN_INGRESS="$AS_FRAUD_SIP"
  GEN_ROUTE_RETURN_ARGS=(--route-return-address 127.0.0.1 --route-return-port "$IMS_RETURN")
  FRAUD_API_ARG=(--fraud-api-url "http://$API_HOST:$AS_FRAUD_API")
  rewrite_rules_to_port "$IMS_RETURN"

  echo "[ims] external chained runtime return:$IMS_RETURN term:$IMS_TERM"
  uv run python -m ims_mock.external_runtime \
    --bind-address 127.0.0.1 \
    --as1-port "$AS_FRAUD_SIP" \
    --as2-port "$AS_TRANS_SIP" \
    --return-port "$IMS_RETURN" \
    --forward-port "$IMS_FORWARD" \
    --terminating-port "$IMS_TERM" \
    --pcscf-port "$IMS_PCSCF" \
    > "$LOG_DIR/ims.log" 2>&1 &
  PIDS+=($!)

  echo "[1/5] anti-fraud AS :$AS_FRAUD_SIP API :$AS_FRAUD_API"
  FRAUD_SIP_LISTEN_PORT="$AS_FRAUD_SIP" \
  FRAUD_INTERNAL_API_PORT="$AS_FRAUD_API" \
  FRAUD_INTERNAL_API_ADDRESS="$BIND_ADDR" \
  FRAUD_SBC_PEER_ADDRESS=127.0.0.1 \
  FRAUD_SBC_PEER_PORT="$IMS_RETURN" \
  FRAUD_ALLOWED_PEERS=127.0.0.1 \
    uv run python -m anti_fraud_as.main \
    > "$LOG_DIR/fraud.log" 2>&1 &
  PIDS+=($!)
else
  rewrite_rules_to_port "$CORE_SIP"

  echo "[0/4] core mock :$CORE_SIP (UAS) trunk :$CORE_UAC (UAC)"
  uv run python -m s_sbc_mock.main \
    --listen-port "$CORE_SIP" \
    --trunk-port "$CORE_UAC" \
    > "$LOG_DIR/core.log" 2>&1 &
  PIDS+=($!)
fi

echo "[2/5] translation AS :$AS_TRANS_SIP API :$AS_TRANS_API"
if [[ "$MODE" == "full" ]]; then
  SBC_PEER_PORT="$IMS_RETURN"
else
  SBC_PEER_PORT="$CORE_SIP"
fi
SBC_PEER_ADDRESS=127.0.0.1 \
SBC_PEER_PORT="$SBC_PEER_PORT" \
SIP_LISTEN_PORT="$AS_TRANS_SIP" \
INTERNAL_API_ADDRESS="$BIND_ADDR" \
INTERNAL_API_PORT="$AS_TRANS_API" \
  uv run python -m as_app.main \
  > "$LOG_DIR/trans.log" 2>&1 &
PIDS+=($!)

echo "[3/5] load generator topology=$GEN_TOPOLOGY ingress :$GEN_INGRESS HTTP :$GEN_HTTP"
uv run python tools/call_load_generator.py \
  --topology "$GEN_TOPOLOGY" \
  --ingress-port "$GEN_INGRESS" \
  --as-port "$GEN_INGRESS" \
  "${GEN_ROUTE_RETURN_ARGS[@]}" \
  --local-address "127.0.0.1" \
  --local-port "$GEN_SIP" \
  --http-address "$BIND_ADDR" \
  --http-port "$GEN_HTTP" \
  > "$LOG_DIR/gen.log" 2>&1 &
PIDS+=($!)

echo "[4/5] console :$CONSOLE_HTTP"
uv run python -m console.main \
  --address "$BIND_ADDR" \
  --port "$CONSOLE_HTTP" \
  --as-api-url "http://$API_HOST:$AS_TRANS_API" \
  --load-api-url "http://$API_HOST:$GEN_HTTP" \
  "${FRAUD_API_ARG[@]}" \
  > "$LOG_DIR/console.log" 2>&1 &
PIDS+=($!)

echo ""
echo "    waiting for ports to bind..."
for port in "$AS_TRANS_API" "$GEN_HTTP" "$CONSOLE_HTTP" "$GEN_INGRESS"; do
  if wait_port "$port"; then
    echo "      :$port  OK"
  else
    echo "      :$port  TIMEOUT — check $LOG_DIR/"
  fi
done
[[ "$MODE" == "full" ]] && wait_port "$IMS_RETURN" && echo "      :$IMS_RETURN (ims return) OK"

echo ""
echo "==> stack ready ($GEN_TOPOLOGY)"
echo "    console (WSL):     http://127.0.0.1:$CONSOLE_HTTP"
[[ -n "$WSL_IP" ]] && echo "    console (Windows): http://$WSL_IP:$CONSOLE_HTTP"
echo "    generator: curl -X POST http://127.0.0.1:$GEN_HTTP/load/start"
echo "    console -> Load Generator -> Start"
echo ""
echo "    ctrl+c to stop everything"

wait
