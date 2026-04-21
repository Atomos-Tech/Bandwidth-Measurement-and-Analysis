#!/usr/bin/env python3
"""
=============================================================================
 Topology 1 — Linear (Point-to-Point)
=============================================================================

   h1 (10.0.0.1) ----[s1]---- h2 (10.0.0.2)
                  100 Mbps, 5 ms

 Tests:
   baseline    TCP + UDP baseline throughput
   streams     Parallel TCP streams (1, 2, 4, 8)
   window      TCP window size effect (16K .. 512K)
   all         All of the above (default)

=============================================================================
"""

import os
import sys
import json
import time
import argparse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from mininet.net  import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log  import setLogLevel, info, error
from mininet.cli  import CLI

RESULTS_DIR = '/tmp/sdn_results'


# ─────────────────────────────────────────────────────────────────────────────
#  Topology
# ─────────────────────────────────────────────────────────────────────────────

def build_net(bw=100, delay='5ms', loss=0):
    net = Mininet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        waitConnected=False,   
    )
    net.addController('c0', ip='127.0.0.1', port=6633)
    # Keep switch config compatible with POX l2_learning (OF1.0 path).
    s1 = net.addSwitch('s1', failMode='standalone')
    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
    opts = dict(bw=bw, delay=delay, loss=loss, use_htb=True)
    net.addLink(h1, s1, **opts)
    net.addLink(h2, s1, **opts)
    return net


# ─────────────────────────────────────────────────────────────────────────────
#  iperf3 helpers
# ─────────────────────────────────────────────────────────────────────────────

def start_server(host, port=5201):
    host.cmd('pkill -9 -f iperf3 2>/dev/null; sleep 0.3')
    host.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf3_svr_{host.name}.log')
    time.sleep(1)

def stop_server(host):
    host.cmd('pkill -9 -f iperf3 2>/dev/null')

def run_iperf3(client, server_ip, label,
               duration=10, udp=False, parallel=1,
               window=None, bandwidth=None, port=5201):
    cmd = f'iperf3 -c {server_ip} -p {port} -t {duration} -J'
    if udp:
        cmd += f' -u -b {bandwidth or "100M"}'
    if parallel > 1:
        cmd += f' -P {parallel}'
    if window:
        cmd += f' -w {window}'

    info(f'    [iperf3] {label}: {cmd}\n')
    raw = client.cmd(cmd)

    result = {
        'label'    : label,
        'protocol' : 'UDP' if udp else 'TCP',
        'parallel' : parallel,
        'duration' : duration,
        'window'   : window,
        'summary'  : {},
        'intervals': [],
    }
    try:
        data = json.loads(raw)
        end  = data.get('end', {})

        if udp:
            s = end.get('sum', {})
            result['summary'] = {
                'Mbps'     : round(s.get('bits_per_second', 0) / 1e6, 3),
                'jitter_ms': round(s.get('jitter_ms', 0), 3),
                'lost_pct' : round(s.get('lost_percent', 0), 2),
            }
        else:
            if parallel > 1:
                s = end.get('sum_received', end.get('sum_sent', {}))
            else:
                s = (end.get('sum_received') or
                     (end.get('streams', [{}])[0].get('receiver', {}) if end.get('streams') else {}))
            result['summary'] = {
                'Mbps'       : round(s.get('bits_per_second', 0) / 1e6, 3),
                'retransmits': end.get('sum_sent', {}).get('retransmits', 0),
            }

        for iv in data.get('intervals', []):
            ivs = iv.get('sum', {})
            result['intervals'].append({
                'start': round(ivs.get('start', 0), 1),
                'Mbps' : round(ivs.get('bits_per_second', 0) / 1e6, 3),
            })

        info(f'    >> {label}: {result["summary"].get("Mbps", 0):.2f} Mbps\n')

    except Exception as exc:
        result['error'] = str(exc)
        error(f'    parse error: {exc}  raw: {raw[:200]}\n')

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Scenarios
# ─────────────────────────────────────────────────────────────────────────────

def scenario_baseline(net):
    h1, h2 = net.get('h1'), net.get('h2')
    results = {}

    info('\n  -- Baseline TCP --\n')
    start_server(h1)
    results['tcp_baseline'] = run_iperf3(h2, h1.IP(), 'TCP Baseline')
    stop_server(h1); time.sleep(0.5)

    info('\n  -- Baseline UDP --\n')
    start_server(h1)
    results['udp_baseline'] = run_iperf3(
        h2, h1.IP(), 'UDP Baseline', udp=True, bandwidth='100M')
    stop_server(h1)
    return results

def scenario_parallel_streams(net):
    h1, h2 = net.get('h1'), net.get('h2')
    results = {}
    for n in [1, 2, 4, 8]:
        info(f'\n  -- Parallel streams N={n} --\n')
        start_server(h1)
        results[f'parallel_{n}'] = run_iperf3(
            h2, h1.IP(), f'TCP {n} stream(s)', parallel=n)
        stop_server(h1); time.sleep(0.5)
    return results

def scenario_window_sizes(net):
    h1, h2 = net.get('h1'), net.get('h2')
    results = {}
    for win in ['16K', '64K', '128K', '256K', '512K']:
        info(f'\n  -- Window size {win} --\n')
        start_server(h1)
        results[f'window_{win}'] = run_iperf3(
            h2, h1.IP(), f'TCP win={win}', window=win)
        stop_server(h1); time.sleep(0.5)
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', default='all', choices=['baseline', 'streams', 'window', 'all'])
    ap.add_argument('--cli',   action='store_true')
    ap.add_argument('--bw',   type=int, default=100)
    ap.add_argument('--delay', default='5ms')
    args = ap.parse_args()

    setLogLevel('info')
    os.makedirs(RESULTS_DIR, exist_ok=True)

    info('\n' + '=' * 62 + '\n')
    info(' TOPOLOGY 1 — Linear Point-to-Point\n')
    info(f' h1(10.0.0.1) --[s1]-- h2(10.0.0.2)\n')
    info(f' bw={args.bw} Mbps  delay={args.delay}\n')
    info('=' * 62 + '\n')

    net = None
    all_results = {
        'topology'      : 'linear',
        'bw_mbps'       : args.bw,
        'delay'         : args.delay,
        'tests'         : {},
    }

    try:
        net = build_net(bw=args.bw, delay=args.delay)
        net.start()

        info('[*] Waiting for controller handshake (5s)...\n')
        time.sleep(5)

        info('[*] Connectivity check:\n')
        loss = net.pingAll(timeout=3)
        all_results['ping_loss_pct'] = loss

        if args.scenario in ('baseline', 'all'):
            all_results['tests']['baseline'] = scenario_baseline(net)
        if args.scenario in ('streams', 'all'):
            all_results['tests']['parallel_streams'] = scenario_parallel_streams(net)
        if args.scenario in ('window', 'all'):
            all_results['tests']['window_sizes'] = scenario_window_sizes(net)

        # Use default ovs-ofctl mode for POX-compatible flow dump.
        s1   = net.get('s1')
        dump = s1.cmd('ovs-ofctl dump-flows s1')
        info('\n[*] Flow table (s1):\n' + dump + '\n')
        all_results['flow_table_dump'] = dump

        if args.cli:
            CLI(net)

    finally:
        if net is not None:
            net.stop()

    out = os.path.join(RESULTS_DIR, 'topology1_linear_results.json')
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    info(f'[*] Results saved -> {out}\n')

if __name__ == '__main__':
    main()
