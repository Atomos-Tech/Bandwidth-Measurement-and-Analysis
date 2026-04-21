#!/usr/bin/env python3
"""
seed_results.py — Seed /tmp/sdn_results with sample results so that
analyze_results.py can generate all graphs without running Mininet.

Usage:
    python3 results/seed_results.py
    python3 analysis/analyze_results.py
"""
import json
import os

# Source sample file shipped in repo.
SAMPLE_FILE = os.path.join(os.path.dirname(__file__), 'sample_results.json')
# Output location expected by topology/analysis workflow.
OUT_DIR     = '/tmp/sdn_results'

# Map each top-level sample key to the output filename.
KEY_TO_FILE = {
    'scenario1_forwarding'     : 'scenario1_forwarding.json',
    'scenario2_firewall'       : 'scenario2_firewall.json',
    'scenario3_qos'            : 'scenario3_qos.json',
    'topology1_linear_results' : 'topology1_linear_results.json',
    'topology2_star_results'   : 'topology2_star_results.json',
    'topology3_tree_results'   : 'topology3_tree_results.json',
}

with open(SAMPLE_FILE) as f:
    sample = json.load(f)

os.makedirs(OUT_DIR, exist_ok=True)

# Write each available sample block as a standalone JSON file.
for key, filename in KEY_TO_FILE.items():
    if key in sample:
        path = os.path.join(OUT_DIR, filename)
        with open(path, 'w') as f:
            json.dump(sample[key], f, indent=2)
        print(f"  Seeded → {path}")

print("\nDone. Now run:  python3 analysis/analyze_results.py")
