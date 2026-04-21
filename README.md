# Bandwidth Measurement and Analysis (4th Sem CN Project)

This README is written based on the current code in this repository.
Prepared as part of a 4th semester Computer Networks project submission.

## Important Grading Note (Read First)

This repo contains two SDN paths:

1. **Active path used by scripts in this repo**
   - `tests/run_all.sh` uses **POX** (`pox/pox.py forwarding.l2_learning`) for topology runs.
   - `tests/scenario*.py` run Mininet in **standalone switch mode** (`controller=None`) and do not use an SDN controller process.
   - Firewall in scenario 2 is injected with `ovs-ofctl`.
   - QoS in scenario 3 is enforced using Linux `tc tbf` (host-side), not OpenFlow meters.

2. **Optional path included in repo but not used by `run_all.sh`**
   - `controller/bandwidth_controller.py` (Ryu, OpenFlow 1.3) exists, but current automation does not invoke it.

If evaluation is based on actual code execution, this README matches that behavior.

---

## 1) Problem Statement

Measure and compare network performance (primarily throughput, plus connectivity and latency context) across SDN-style Mininet topologies using `iperf3` and flow inspection.

Topologies tested:
- Linear
- Star
- Tree

Scenarios tested:
- Forwarding throughput (TCP/UDP/parallel streams)
- Firewall behavior (allowed vs blocked flow)
- QoS behavior (rate-limited vs unlimited)

---

## 2) Setup (Ubuntu 24.04)

### Prerequisites
- Ubuntu 24.04 LTS
- Internet access
- `sudo` privileges

### One-shot setup

```bash
git clone https://github.com/Atomos-Tech/Bandwidth-Measurement-and-Analysis.git
cd bandwidth-analysis-sdn
sudo bash setup.sh
```

`setup.sh` installs/rebuilds:
- Mininet
- Open vSwitch
- iperf3
- POX controller (fangtooth branch)
- Python packages needed for analysis (`matplotlib`, `numpy`, `pyasyncore`)

### Quick verification

```bash
mn --version
iperf3 --version
python3 pox/pox.py --help | head -n 3
```

---

## 3) Execution Steps

Run these three commands from the project root:

```bash
sudo bash setup.sh
sudo bash tests/run_all.sh
sudo python3 analysis/analyze_results.py
```

What each command does:
1. `sudo bash setup.sh`
   Installs/repairs environment dependencies (Mininet, OVS, POX, Python packages).
2. `sudo bash tests/run_all.sh`
   Runs all scenarios and topology scripts, then triggers analysis.
3. `sudo python3 analysis/analyze_results.py`
   Regenerates result summary and graph artifacts explicitly.

---

## 4) Expected Output

Expect these artifacts after execution.

### A. Scenario JSON outputs (repo-local)

- `results/scenario1_forwarding.json`
- `results/scenario2_firewall.json`
- `results/scenario3_qos.json`

Typical expectations:
- Scenario 1: TCP and UDP throughput fields in Mbps
- Scenario 2: allowed flow has non-zero Mbps; blocked flow near 0 Mbps
- Scenario 3: unlimited host high Mbps, limited hosts near configured caps (implemented via `tc`)

### B. Topology JSON outputs (`/tmp`)

- `/tmp/sdn_results/topology1_linear_results.json`
- `/tmp/sdn_results/topology2_star_results.json`
- `/tmp/sdn_results/topology3_tree_results.json`

These include test dictionaries and flow table dump strings from `ovs-ofctl dump-flows`.

### C. Graph outputs

- `results/graphs/bar_topology_comparison.png`
- `results/graphs/bar_protocol_comparison.png`
- `results/graphs/bar_parallel_streams.png`
- `results/graphs/bar_window_sizes.png`
- `results/graphs/bar_firewall.png`
- `results/graphs/bar_qos.png`
- `results/graphs/bar_intra_vs_inter.png`
- `results/graphs/bar_simultaneous.png`

Notes:
- Graph script reads files under `results/`.
- Topology scripts write to `/tmp/sdn_results/`.
- For topology graphs from fresh topology runs, copy files first:

```bash
cp /tmp/sdn_results/topology*_results.json results/
python3 analysis/analyze_results.py
```

### D. Runtime log

- `results/run_all.log`
