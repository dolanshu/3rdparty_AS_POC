#!/usr/bin/env bash
# Capture SIP traffic on the trunk for acceptance evidence (AGENT.md section 4.8).
#
# Usage:
#   ./tools/capture.sh                 # capture UDP 5060 and the mock ports
#   ./tools/capture.sh --port 5060     # capture a single port
#   ./tools/capture.sh --list          # show the captures that exist
#
# Captures are written to captures/ (gitignored) and are never committed: committing
# captures of real traffic is forbidden by AGENT.md section 13.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CAPTURE_DIR="${REPO_ROOT}/captures"
PORTS=(5060 15060 15061)
DURATION="${DURATION:-60}"

usage() {
  grep '^#' "$0" | sed -n '2,12p' | sed 's/^# \{0,1\}//'
}

list_captures() {
  mkdir -p "$CAPTURE_DIR"
  ls -1 "$CAPTURE_DIR" 2>/dev/null || echo "(no captures yet)"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORTS=("$2"); shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --list) list_captures; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$CAPTURE_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${CAPTURE_DIR}/trunk-${STAMP}.pcap"

FILTER="udp and (port $(IFS=' or port '; echo "${PORTS[*]}"))"

if ! command -v tcpdump >/dev/null 2>&1; then
  echo "tcpdump is not installed; install it or capture from the container:" >&2
  echo "  docker run --rm --net=host -v \$(pwd)/captures:/captures corfr/tcpdump -w /captures/trunk.pcap -G ${DURATION} -W 1 ${FILTER}" >&2
  exit 1
fi

echo "capturing: ${FILTER}"
echo "output:    ${OUT}"
echo "duration:  ${DURATION}s (Ctrl-C to stop earlier)"
# shellcheck disable=SC2086
tcpdump -i any -nn -s 0 -G "${DURATION}" -W 1 -w "${OUT}" ${FILTER}
echo "written: ${OUT}"
