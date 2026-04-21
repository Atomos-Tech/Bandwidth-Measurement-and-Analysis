#!/usr/bin/env python3
"""
Generate summary graphs from scenario/topology JSON outputs.

This script is kept simple for project-demo use:
- safe JSON loading
- common Mbps parser
- bar charts for each scenario comparison
"""

import os
import sys
import json
import glob
import argparse
import warnings
warnings.filterwarnings('ignore')

try:
    # Use non-interactive backend so script works in terminal-only environments.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[WARNING] matplotlib not installed — skipping graphs")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_DIR, 'results')
GRAPHS_DIR  = os.path.join(RESULTS_DIR, 'graphs')

C_BLUE   = '#2196F3'
C_GREEN  = '#4CAF50'
C_RED    = '#F44336'
C_ORANGE = '#FF9800'
C_PURPLE = '#9C27B0'
C_TEAL   = '#009688'
COLORS = [C_BLUE, C_GREEN, C_RED, C_ORANGE, C_PURPLE, C_TEAL]

def load_json(path):
    """Load JSON safely; return empty dict if file is missing/corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        return {}

def safe_mbps(obj):
    """Extract Mbps from multiple result formats used in this project."""
    if isinstance(obj, (int, float)): return float(obj)
    if isinstance(obj, dict):
        for key in ('Mbps', 'mbps', 'bps'):
            if key in obj:
                return obj[key] / 1e6 if key == 'bps' else float(obj[key])
        if 'summary' in obj: return safe_mbps(obj['summary'])
    return 0.0

def styled_bar(ax, x, heights, labels, colors=None, xlabel='', ylabel='Throughput (Mbps)', title='', show_values=True, ylim=None):
    """Shared chart style used by all bar-plot functions."""
    if colors is None: colors = [COLORS[i % len(COLORS)] for i in range(len(x))]
    bars = ax.bar(x, heights, color=colors, edgecolor='white', linewidth=0.8, zorder=3)
    ax.set_xticks(range(len(x)))
    ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=9)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_title(title, fontsize=12, fontweight='bold', pad=8)
    ax.yaxis.grid(True, linestyle='--', alpha=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    if ylim: ax.set_ylim(ylim)
    if show_values:
        for bar in bars:
            h = bar.get_height()
            if h > 0: ax.text(bar.get_x() + bar.get_width() / 2, h + 0.3, f'{h:.1f}', ha='center', va='bottom', fontsize=8, fontweight='bold')
    return bars

def save(fig, name):
    """Save chart to results/graphs with consistent quality settings."""
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    path = os.path.join(GRAPHS_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)

def graph_topology_comparison():
    """Compare average throughput across linear, star, and tree cases."""
    data = {}
    d = load_json(os.path.join(RESULTS_DIR, 'topology1_linear_results.json'))
    if d: data['Linear\n(P2P)'] = safe_mbps(d.get('tests', {}).get('baseline', {}).get('tcp_baseline', {}))
    d = load_json(os.path.join(RESULTS_DIR, 'topology2_star_results.json'))
    if d:
        vals = [safe_mbps(v) for v in d.get('tests', {}).get('sequential', {}).values() if safe_mbps(v) > 0]
        if vals: data['Star\n(avg client)'] = sum(vals) / len(vals)
    d = load_json(os.path.join(RESULTS_DIR, 'topology3_tree_results.json'))
    if d:
        vals = [safe_mbps(v) for v in d.get('tests', {}).get('intra_subtree', {}).values() if safe_mbps(v) > 0]
        if vals: data['Tree\n(intra-subtree)'] = sum(vals) / len(vals)
        vals2 = [safe_mbps(v) for v in d.get('tests', {}).get('inter_subtree', {}).values() if safe_mbps(v) > 0 and not isinstance(v, str)]
        if vals2: data['Tree\n(inter-subtree)'] = sum(vals2) / len(vals2)
    if not data: return
    fig, ax = plt.subplots(figsize=(9, 5))
    labels, heights = list(data.keys()), list(data.values())
    styled_bar(ax, range(len(labels)), heights, labels, title='Throughput Comparison Across Topologies', ylabel='Throughput (Mbps)', ylim=(0, max(heights) * 1.25 + 5))
    save(fig, 'bar_topology_comparison.png')

def graph_protocol_comparison():
    """Compare TCP and UDP baseline throughput on linear topology."""
    d = load_json(os.path.join(RESULTS_DIR, 'topology1_linear_results.json')) or load_json(os.path.join(RESULTS_DIR, 'scenario1_forwarding.json'))
    if not d: return
    base = d.get('tests', {}).get('baseline', d.get('tests', {}))
    tcp, udp = safe_mbps(base.get('tcp_baseline', {})), safe_mbps(base.get('udp_baseline', {}))
    if tcp == 0 and udp == 0: return
    fig, ax = plt.subplots(figsize=(6, 5))
    styled_bar(ax, range(2), [tcp, udp], ['TCP', 'UDP'], colors=[C_BLUE, C_ORANGE], title='TCP vs UDP Throughput\n(Linear Topology, 100 Mbps link, 10s)', ylim=(0, max(tcp, udp) * 1.4 + 5))
    save(fig, 'bar_protocol_comparison.png')

def graph_parallel_streams():
    """Plot throughput change with 1/2/4/8 parallel TCP streams."""
    d = load_json(os.path.join(RESULTS_DIR, 'topology1_linear_results.json'))
    if not d: return
    streams = d.get('tests', {}).get('parallel_streams', {})
    if not streams: return
    mapping = {n: safe_mbps(v) for k, v in streams.items() for n in (1, 2, 4, 8) if str(n) in k}
    if not mapping: return
    ns = sorted(mapping.keys())
    heights = [mapping[n] for n in ns]
    labels = [f'{n} stream{"s" if n > 1 else ""}' for n in ns]
    fig, ax = plt.subplots(figsize=(7, 5))
    styled_bar(ax, range(len(ns)), heights, labels, colors=[COLORS[i] for i in range(len(ns))], title='TCP Throughput vs Number of Parallel Streams', ylim=(0, max(heights) * 1.3 + 5))
    save(fig, 'bar_parallel_streams.png')

def graph_window_sizes():
    """Plot throughput for different TCP socket window sizes."""
    d = load_json(os.path.join(RESULTS_DIR, 'topology1_linear_results.json'))
    if not d: return
    win_data = d.get('tests', {}).get('window_sizes', {})
    if not win_data: return
    labels, heights = [], []
    for win in ['16K', '64K', '128K', '256K', '512K']:
        if f'window_{win}' in win_data:
            labels.append(win)
            heights.append(safe_mbps(win_data[f'window_{win}']))
    if not heights: return
    fig, ax = plt.subplots(figsize=(8, 5))
    styled_bar(ax, range(len(labels)), heights, labels, colors=COLORS[:len(labels)], title='TCP Throughput vs Socket Window Size', ylim=(0, max(heights) * 1.3 + 5))
    save(fig, 'bar_window_sizes.png')

def graph_firewall():
    """Show allowed vs blocked firewall flow performance."""
    d = load_json(os.path.join(RESULTS_DIR, 'scenario2_firewall.json'))
    if not d: return
    tests = d.get('tests', {})
    heights = [safe_mbps(tests.get('allowed_h2_to_h1', {})), safe_mbps(tests.get('blocked_h3_to_h1', {})), safe_mbps(tests.get('allowed_h4_to_h2', {}))]
    labels = ['h2 → h1\n(Allowed)', 'h3 → h1\n(Blocked by SDN)', 'h4 → h2\n(Allowed, no rule)']
    fig, ax = plt.subplots(figsize=(7, 5))
    styled_bar(ax, range(3), heights, labels, colors=[C_GREEN, C_RED, C_GREEN], title='Firewall Effect: Allowed vs SDN-Blocked Traffic', ylim=(0, max(heights) * 1.4 + 5))
    ax.text(1, heights[1] + 1, 'BLOCKED', ha='center', va='bottom', fontsize=8, color=C_RED, fontweight='bold')
    save(fig, 'bar_firewall.png')

def graph_qos():
    """Show unlimited vs limited host throughput for QoS scenario."""
    d = load_json(os.path.join(RESULTS_DIR, 'scenario3_qos.json'))
    if not d: return
    tests = d.get('tests', {})
    heights = [safe_mbps(tests.get('unlimited_h2', {})), safe_mbps(tests.get('limited_h3', {})), safe_mbps(tests.get('limited_h4', {}))]
    labels = ['h2\n(Unlimited)', 'h3\n(Meter: 2 Mbps)', 'h4\n(Meter: 5 Mbps)']
    fig, ax = plt.subplots(figsize=(7, 5))
    styled_bar(ax, range(3), heights, labels, colors=[C_GREEN, C_RED, C_ORANGE], title='QoS Rate Limiting via OpenFlow Meters', ylim=(0, max(heights) * 1.4 + 5))
    if heights[1] > 0: ax.axhline(2, color=C_RED, linestyle='--', alpha=0.7, label='2 Mbps limit')
    if heights[2] > 0: ax.axhline(5, color=C_ORANGE, linestyle='--', alpha=0.7, label='5 Mbps limit')
    ax.legend(fontsize=9)
    save(fig, 'bar_qos.png')

def graph_tcp_timeseries():
    # Placeholder kept for future extension.
    pass

def graph_intra_vs_inter():
    """Compare intra-subtree vs inter-subtree throughput in tree topology."""
    d = load_json(os.path.join(RESULTS_DIR, 'topology3_tree_results.json'))
    if not d: return
    tests = d.get('tests', {})
    entries = [(k.replace('_', '\n'), safe_mbps(v), C_BLUE) for k, v in tests.get('intra_subtree', {}).items() if safe_mbps(v) > 0]
    entries += [(k.replace('_', '\n'), safe_mbps(v), C_ORANGE) for k, v in tests.get('inter_subtree', {}).items() if 'udp' not in k.lower() and safe_mbps(v) > 0]
    if not entries: return
    labels, heights, colors = [e[0] for e in entries], [e[1] for e in entries], [e[2] for e in entries]
    fig, ax = plt.subplots(figsize=(9, 5))
    styled_bar(ax, range(len(labels)), heights, labels, colors=colors, title='Tree Topology: Intra-Subtree vs Inter-Subtree', ylim=(0, max(heights) * 1.35 + 5))
    save(fig, 'bar_intra_vs_inter.png')

def graph_simultaneous():
    """Compare sequential and simultaneous client throughput in star topology."""
    d = load_json(os.path.join(RESULTS_DIR, 'topology2_star_results.json'))
    if not d: return
    seq, simul = d.get('tests', {}).get('sequential', {}), d.get('tests', {}).get('simultaneous', {})
    groups = {hn: (safe_mbps(seq.get(f'seq_{hn}', {})), safe_mbps(simul.get(f'simul_{hn}', {}))) for hn in ['h2', 'h3', 'h4'] if safe_mbps(seq.get(f'seq_{hn}')) > 0 or safe_mbps(simul.get(f'simul_{hn}')) > 0}
    if not groups: return
    names = list(groups.keys())
    seq_v, simul_v = [groups[n][0] for n in names], [groups[n][1] for n in names]
    x, width = np.arange(len(names)), 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - width/2, seq_v, width, label='Sequential', color=C_BLUE)
    ax.bar(x + width/2, simul_v, width, label='Simultaneous', color=C_ORANGE)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.legend(fontsize=9)
    save(fig, 'bar_simultaneous.png')

def graph_summary_table():
    # Placeholder kept for future extension.
    pass

def print_console_report():
    """Print quick Mbps summary in terminal for report snapshots."""
    print('\n' + '=' * 62 + '\n BANDWIDTH MEASUREMENT & ANALYSIS — RESULTS SUMMARY\n' + '=' * 62)
    print('\n' + '-' * 62 + '\n Key Metrics\n' + '-' * 62)
    d = load_json(os.path.join(RESULTS_DIR, 'scenario1_forwarding.json'))
    if d:
        t = d.get('tests', {})
        print(f"  Scenario 1  TCP baseline:    {safe_mbps(t.get('tcp_baseline')):7.2f} Mbps")
        print(f"  Scenario 1  UDP baseline:    {safe_mbps(t.get('udp_baseline')):7.2f} Mbps")
        print(f"  Scenario 1  TCP 4 streams:   {safe_mbps(t.get('tcp_parallel')):7.2f} Mbps")
    d = load_json(os.path.join(RESULTS_DIR, 'scenario2_firewall.json'))
    if d:
        t = d.get('tests', {})
        print(f"  Scenario 2  h2→h1 allowed:  {safe_mbps(t.get('allowed_h2_to_h1')):7.2f} Mbps")
        print(f"  Scenario 2  h3→h1 blocked:  {safe_mbps(t.get('blocked_h3_to_h1')):7.2f} Mbps")
    d = load_json(os.path.join(RESULTS_DIR, 'scenario3_qos.json'))
    if d:
        t = d.get('tests', {})
        print(f"  Scenario 3  h2 unlimited:   {safe_mbps(t.get('unlimited_h2')):7.2f} Mbps")
        print(f"  Scenario 3  h3 2Mbps limit: {safe_mbps(t.get('limited_h3')):7.2f} Mbps")
        print(f"  Scenario 3  h4 5Mbps limit: {safe_mbps(t.get('limited_h4')):7.2f} Mbps")

def main():
    # Graceful exit when matplotlib is not present in environment.
    if not HAS_MPL: return
    print_console_report()
    graph_topology_comparison()
    graph_protocol_comparison()
    graph_parallel_streams()
    graph_window_sizes()
    graph_firewall()
    graph_qos()
    graph_intra_vs_inter()
    graph_simultaneous()

if __name__ == '__main__':
    main()
