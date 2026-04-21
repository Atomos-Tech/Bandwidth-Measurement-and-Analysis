#!/usr/bin/env python3
"""
=============================================================================
 Topology 3 — Tree (Two-Level Switching Hierarchy)
=============================================================================

              [s1]  <- core switch
             /    \
          [s2]    [s3]   <- edge switches
         /  \    /  \
        h1  h2  h3   h4

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


def build_net(bw=100, delay='3ms', core_delay='5ms', loss=0):
    net = Mininet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        waitConnected=False,
    )
    net.addController('c0', ip='127.0.0.1', port=6633)

    # Keep switch config compatible with POX l2_learning (OF1.0 path).
    s1 = net.addSwitch('s1', failMode='standalone')  # core
    s2 = net.addSwitch('s2', failMode='standalone')  # left edge
    s3 = net.addSwitch('s3', failMode='standalone')  # right edge

    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
    h4 = net.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

    core_opts = dict(bw=bw, delay=core_delay, loss=loss, use_htb=True)
    net.addLink(s1, s2, **core_opts)
    net.addLink(s1, s3, **core_opts)

    edge_opts = dict(bw=bw, delay=delay, loss=loss, use_htb=True)
    net.addLink(h1, s2, **edge_opts)
    net.addLink(h2, s2, **edge_opts)
    net.addLink(h3, s3, **edge_opts)
    net.addLink(h4, s3, **edge_opts)

    return net

def start_server(host, port=5201):
    host.cmd('pkill -9 -f iperf3 2>/dev/null; sleep 0.3')
    host.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf3_tree_{host.name}.log')
    time.sleep(1)

def stop_server(host):
    host.cmd('pkill -9 -f iperf3 2>/dev/null')

def run_iperf3(client, server_ip, label, duration=10,
               udp=False, bandwidth=None, port=5201):
    cmd = f'iperf3 -c {server_ip} -p {port} -t {duration} -J'
    if udp:
        cmd += f' -u -b {bandwidth or "100M"}'

    info(f'    [iperf3] {label}: {cmd}\n')
    raw = client.cmd(cmd)

    result = {
        'label'    : label,
        'protocol' : 'UDP' if udp else 'TCP',
        'duration' : duration,
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

def dump_flows(net, sw):
    # Use default ovs-ofctl mode for POX-compatible flow dump.
    return net.get(sw).cmd(f'ovs-ofctl dump-flows {sw}')

def scenario_intra_subtree(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h3, h4 = net.get('h3'), net.get('h4')
    results = {}

    info('\n  -- Intra: h1 -> h2 (same subtree, ~1 hop) --\n')
    start_server(h2)
    results['h1_to_h2'] = run_iperf3(h1, h2.IP(), 'h1->h2 intra-left')
    stop_server(h2)
    time.sleep(0.5)

    info('\n  -- Intra: h3 -> h4 (same subtree, ~1 hop) --\n')
    start_server(h4)
    results['h3_to_h4'] = run_iperf3(h3, h4.IP(), 'h3->h4 intra-right')
    stop_server(h4)
    return results

def scenario_inter_subtree(net):
    h1, h2 = net.get('h1'), net.get('h2')
    h3, h4 = net.get('h3'), net.get('h4')
    results = {}

    info('\n  -- Inter: h1 -> h3 (cross-subtree, ~3 hops) --\n')
    start_server(h3)
    results['h1_to_h3'] = run_iperf3(h1, h3.IP(), 'h1->h3 inter-subtree')
    stop_server(h3)
    time.sleep(0.5)

    info('\n  -- Inter: h2 -> h4 (cross-subtree, ~3 hops) --\n')
    start_server(h4)
    results['h2_to_h4'] = run_iperf3(h2, h4.IP(), 'h2->h4 inter-subtree')
    stop_server(h4)
    time.sleep(0.5)

    info('\n  -- Inter: h1 -> h3 UDP --\n')
    start_server(h3)
    results['h1_to_h3_udp'] = run_iperf3(h1, h3.IP(), 'h1->h3 UDP inter', udp=True, bandwidth='100M')
    stop_server(h3)
    return results

def scenario_ping_rtt(net):
    results = {}
    pairs = [
        ('h1', 'h2', 'intra-left',  1),
        ('h3', 'h4', 'intra-right', 1),
        ('h1', 'h3', 'inter',       3),
        ('h2', 'h4', 'inter',       3),
    ]
    for src_name, dst_name, label, hops in pairs:
        src = net.get(src_name)
        dst = net.get(dst_name)
        info(f'\n  -- Ping: {src_name} -> {dst_name} ({label}, ~{hops} hops) --\n')
        out = src.cmd(f'ping -c 10 -i 0.2 -W 2 {dst.IP()}')
        info(out + '\n')

        rtt_avg = None
        for line in out.splitlines():
            if 'rtt min' in line or 'round-trip' in line:
                try:
                    rtt_avg = float(line.split('=')[-1].strip().split('/')[1])
                except Exception:
                    pass

        results[f'{src_name}_to_{dst_name}'] = {
            'label'   : label,
            'hops'    : hops,
            'rtt_avg' : rtt_avg,
            'raw'     : out,
        }
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', default='all', choices=['intra', 'inter', 'ping', 'all'])
    ap.add_argument('--cli',       action='store_true')
    ap.add_argument('--bw',        type=int, default=100)
    ap.add_argument('--delay',     default='3ms')
    ap.add_argument('--core-delay', default='5ms', dest='core_delay')
    args = ap.parse_args()

    setLogLevel('info')
    os.makedirs(RESULTS_DIR, exist_ok=True)

    info('\n' + '=' * 62 + '\n')
    info(' TOPOLOGY 3 — Tree (2 levels)\n')
    info('         [s1]  (core)\n')
    info('        /     \\\n')
    info('     [s2]     [s3]\n')
    info('     / \\       / \\\n')
    info('   h1   h2   h3   h4\n')
    info(f' bw={args.bw} Mbps  edge_delay={args.delay}  core_delay={args.core_delay}\n')
    info('=' * 62 + '\n')

    net = None
    all_results = {
        'topology'   : 'tree',
        'bw_mbps'    : args.bw,
        'delay'      : args.delay,
        'core_delay' : args.core_delay,
        'tests'      : {},
    }

    try:
        net = build_net(bw=args.bw, delay=args.delay, core_delay=args.core_delay)
        net.start()

        info('[*] Waiting for controller handshake (5s)...\n')
        time.sleep(5)

        info('[*] Connectivity check:\n')
        loss = net.pingAll(timeout=3)
        all_results['ping_loss_pct'] = loss

        if args.scenario in ('intra', 'all'):
            all_results['tests']['intra_subtree'] = scenario_intra_subtree(net)
        if args.scenario in ('inter', 'all'):
            all_results['tests']['inter_subtree'] = scenario_inter_subtree(net)
        if args.scenario in ('ping', 'all'):
            all_results['tests']['ping_rtt'] = scenario_ping_rtt(net)

        for sw_name in ('s1', 's2', 's3'):
            dump = dump_flows(net, sw_name)
            info(f'\n[*] Flow table ({sw_name}):\n{dump}\n')
            all_results[f'flow_table_{sw_name}'] = dump

        if args.cli:
            CLI(net)

    finally:
        if net is not None:
            net.stop()

    out = os.path.join(RESULTS_DIR, 'topology3_tree_results.json')
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    info(f'[*] Results saved -> {out}\n')

if __name__ == '__main__':
    main()
