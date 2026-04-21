#!/usr/bin/env bash
# =============================================================================
#  setup.sh — Project Environment Setup (Ubuntu 24.04 LTS / Python 3.12)
# =============================================================================

set -uo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${YLW}[SETUP] $*${NC}"; }
ok()   { echo -e "${GRN}[OK]    $*${NC}"; }
err()  { echo -e "${RED}[ERR]   $*${NC}"; exit 1; }

if [[ $EUID -ne 0 ]]; then
    err "Run as root: sudo bash setup.sh"
fi

step "1/4 System Update & Core Tools"
apt-get update -qq
apt-get install -y git curl wget build-essential python3 python3-pip \
    net-tools iproute2 iputils-ping tcpdump iperf3 \
    openvswitch-switch openvswitch-common bridge-utils 2>/dev/null || true
ok "Core tools installed"

step "2/4 Mininet"
if ! command -v mn &>/dev/null; then
    apt-get install -y -qq mininet 2>/dev/null || true
fi
command -v mn &>/dev/null && ok "Mininet installed" || err "Mininet failed"

step "3/4 POX Controller (Clean Rebuild)"
# Re-clone POX to avoid stale local state from earlier failed installs.
rm -rf pox
git clone https://github.com/noxrepo/pox.git
cd pox
# Fangtooth branch provides stable Python 3 support for this project setup.
git checkout fangtooth
cd ..
ok "POX completely rebuilt on the Python 3 fangtooth branch"

step "4/4 Python 3.12 Compatibility Patch"
# Python 3.12 removed asyncore from stdlib, so pyasyncore is installed here.
pip3 install --break-system-packages pyasyncore matplotlib numpy 2>/dev/null || true
ok "pyasyncore and Python analysis libs installed"

mkdir -p /tmp/sdn_results/graphs
chmod -R 777 /tmp/sdn_results

echo -e "\n${GRN}Setup Complete! The controller will now survive.${NC}\n"
