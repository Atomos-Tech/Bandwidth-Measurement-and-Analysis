#!/usr/bin/env bash
# =============================================================================
#  run_all.sh — POX Edition
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_DIR/results"
LOG_FILE="$RESULTS_DIR/run_all.log"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'

banner() {
    echo -e "\n${BLU}╔══════════════════════════════════════════════════════════╗${NC}"
    printf "${BLU}║  %-56s║${NC}\n" "$1"
    echo -e "${BLU}╚══════════════════════════════════════════════════════════╝${NC}\n"
}
step() { echo -e "${YLW}[STEP] $*${NC}"; }
ok()   { echo -e "${GRN}[OK]   $*${NC}"; }
err()  { echo -e "${RED}[ERR]  $*${NC}"; }

if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root: sudo bash tests/run_all.sh"
    exit 1
fi

mkdir -p "$RESULTS_DIR" "$RESULTS_DIR/graphs"
exec &> >(tee -a "$LOG_FILE")
echo "$(date): Starting full test suite with POX" >> "$LOG_FILE"

cleanup() {
    # Reset Mininet, controller, and iperf state before each stage.
    echo "[cleanup] Resetting Mininet and POX state..."
    mn -c 2>/dev/null || true
    pkill -9 -f pox.py 2>/dev/null || true
    pkill -9 -f iperf3 2>/dev/null || true
    sleep 2
}

cleanup
banner "Scenario 1: Forwarding & Throughput"
step "Running scenario1_forwarding.py ..."
python3 "$SCRIPT_DIR/scenario1_forwarding.py" && ok "Scenario 1 complete" || err "Scenario 1 failed"
cleanup

banner "Scenario 2: Firewall (Allowed vs Blocked)"
step "Running scenario2_firewall.py ..."
python3 "$SCRIPT_DIR/scenario2_firewall.py" && ok "Scenario 2 complete" || err "Scenario 2 failed"
cleanup

banner "Scenario 3: QoS Rate Limiting"
step "Running scenario3_qos.py ..."
python3 "$SCRIPT_DIR/scenario3_qos.py" && ok "Scenario 3 complete" || err "Scenario 3 failed"
cleanup

start_pox() {
    local logfile="$1"
    # Start POX in background and store logs per topology run.
    python3 "$PROJECT_DIR/pox/pox.py" forwarding.l2_learning > "$logfile" 2>&1 &
    echo $!
}

run_topology() {
    local name="$1"; local script="$2"; local logfile="$3"; shift 3
    # Common wrapper used by linear/star/tree runs.
    banner "Topology: $name"
    step "Starting POX controller..."
    local pid
    pid=$(start_pox "$logfile")
    sleep 3
    step "Running $script ..."
    python3 "$PROJECT_DIR/topologies/$script" "$@" && ok "$name complete" || err "$name failed"
    kill "$pid" 2>/dev/null || true
    cleanup
}

run_topology "Linear" "linear_topo.py" "/tmp/pox_topo1.log" --scenario all
run_topology "Star" "star_topo.py" "/tmp/pox_topo2.log" --scenario sequential
run_topology "Tree" "tree_topo.py" "/tmp/pox_topo3.log" --scenario all

# Final report graphs are generated from collected JSON outputs.
banner "Generating Analysis Graphs"
python3 "$PROJECT_DIR/analysis/analyze_results.py" || true

banner "All Done"
echo -e "${GRN}Check $RESULTS_DIR for JSON results and graphs.${NC}"
