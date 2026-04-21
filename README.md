# Bandwidth Measurement and Analysis

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


### D. Runtime log

- `results/run_all.log`
