#!/usr/bin/env python3
"""
=============================================================================
 Topology 2 — Star (Multiple Clients, One Switch, One Server)
=============================================================================

          h1 (10.0.0.1)  <- server
               |
              [s1]   100 Mbps, 2 ms links
           /   |   \
        h2   h3    h4   <- clients
   (10.0.0.2) (10.0.0.3) (10.0.0.4)

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


def build_net(bw=100, delay='2ms', loss=0):
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
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
    h4 = net.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')
    opts = dict(bw=bw, delay=delay, loss=loss, use_htb=True)
    for h in (h1, h2, h3, h4):
        net.addLink(h, s1, **opts)
    return net

def start_server(host, port=5201):
    host.cmd('pkill -9 -f iperf3 2>/dev/null; sleep 0.3')
    host.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf3_svr_{host.name}.log')
    time.sleep(1)

def stop_server(host):
    host.cmd('pkill -9 -f iperf3 2>/dev/null')

def run_iperf3(client, server_ip, label,
               duration=10, udp=False, parallel=1,
               bandwidth=None, port=5201):
    cmd = f'iperf3 -c {server_ip} -p {port} -t {duration} -J'
    if udp:
        cmd += f' -u -b {bandwidth or "100M"}'
    if parallel > 1:
        cmd += f' -P {parallel}'

    info(f'    [iperf3] {label}: {cmd}\n')
    raw = client.cmd(cmd)

    result = {
        'label'    : label,
        'protocol' : 'UDP' if udp else 'TCP',
        'parallel' : parallel,
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

def dump_flows(net, sw='s1'):
    # Use default ovs-ofctl mode for POX-compatible flow dump.
    return net.get(sw).cmd(f'ovs-ofctl dump-flows {sw}')


def scenario_sequential(net):
    h1 = net.get('h1')
    results = {}
    for name in ('h2', 'h3', 'h4'):
        h = net.get(name)
        info(f'\n  -- Sequential: {name} -> h1 --\n')
        start_server(h1)
        results[f'seq_{name}'] = run_iperf3(h, h1.IP(), f'{name}->h1 seq')
        stop_server(h1)
        time.sleep(0.5)
    return results

def scenario_simultaneous(net):
    h1 = net.get('h1')
    h2, h3, h4 = net.get('h2'), net.get('h3'), net.get('h4')
    results = {}

    PORTS = {'h2': 5202, 'h3': 5203, 'h4': 5204}
    for port in PORTS.values():
        h1.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf3_simul_{port}.log')
    time.sleep(1)

    info('\n  -- Simultaneous: h2, h3, h4 -> h1 (12s) --\n')
    DUR = 12
    h2.cmd(f'iperf3 -c {h1.IP()} -p 5202 -t {DUR} -J > /tmp/r_h2.json 2>&1 &')
    h3.cmd(f'iperf3 -c {h1.IP()} -p 5203 -t {DUR} -J > /tmp/r_h3.json 2>&1 &')
    h4.cmd(f'iperf3 -c {h1.IP()} -p 5204 -t {DUR} -J > /tmp/r_h4.json 2>&1 &')
    time.sleep(DUR + 4)

    for name in ('h2', 'h3', 'h4'):
        fpath = f'/tmp/r_{name}.json'
        try:
            with open(fpath) as f:
                d = json.load(f)
            s    = (d.get('end', {}).get('sum_received') or
                    d.get('end', {}).get('sum_sent', {}))
            mbps = s.get('bits_per_second', 0) / 1e6
            results[f'simul_{name}'] = {
                'label'  : f'{name}->h1 simultaneous',
                'Mbps'   : round(mbps, 3),
                'summary': {'Mbps': round(mbps, 3)},
            }
            info(f'    {name}: {mbps:.2f} Mbps\n')
        except Exception as exc:
            error(f'    {name} result error: {exc}\n')
            results[f'simul_{name}'] = {'error': str(exc)}

    h1.cmd('pkill -9 -f iperf3 2>/dev/null')
    return results

def scenario_firewall(net):
    h1, h2, h3, h4 = (net.get(x) for x in ('h1', 'h2', 'h3', 'h4'))
    results = {}

    info('\n  -- Firewall: h2 -> h1 (ALLOWED) --\n')
    start_server(h1)
    r_allow = run_iperf3(h2, h1.IP(), 'h2->h1 allowed', duration=8)
    stop_server(h1)
    results['allowed_h2'] = r_allow
    time.sleep(0.5)

    info('\n  -- Firewall: h3 -> h1 (BLOCKED) --\n')
    start_server(h1)
    r_block = run_iperf3(h3, h1.IP(), 'h3->h1 blocked', duration=5)
    stop_server(h1)
    results['blocked_h3'] = r_block
    time.sleep(0.5)

    info('\n  -- Ping h4 -> h1 (should pass, ICMP not blocked) --\n')
    ping_out = h4.cmd(f'ping -c 5 -W 2 {h1.IP()}')
    info(ping_out + '\n')
    results['ping_h4_to_h1'] = ping_out
    return results

def scenario_qos(net):
    h1, h2, h3 = net.get('h1'), net.get('h2'), net.get('h3')
    results = {}

    info('\n  -- QoS: h2 -> h1 (UNLIMITED) --\n')
    start_server(h1)
    results['unlimited_h2'] = run_iperf3(h2, h1.IP(), 'h2->h1 unlimited', duration=10)
    stop_server(h1)
    time.sleep(0.5)

    info('\n  -- QoS: h3 -> h1 (RATE-LIMITED ~2 Mbps) --\n')
    start_server(h1)
    results['limited_h3'] = run_iperf3(h3, h1.IP(), 'h3->h1 limited', duration=10)
    stop_server(h1)
    return results

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', default='all', choices=['sequential', 'simultaneous', 'firewall', 'qos', 'all'])
    ap.add_argument('--cli',   action='store_true')
    ap.add_argument('--bw',   type=int, default=100)
    ap.add_argument('--delay', default='2ms')
    args = ap.parse_args()

    setLogLevel('info')
    os.makedirs(RESULTS_DIR, exist_ok=True)

    info('\n' + '=' * 62 + '\n')
    info(' TOPOLOGY 2 — Star\n')
    info(f'        h1 (server)\n')
    info(f'         |[s1]\n')
    info(f' h2  h3  h4 (clients)\n')
    info(f' bw={args.bw} Mbps  delay={args.delay}\n')
    info('=' * 62 + '\n')

    net = None
    all_results = {
        'topology': 'star',
        'bw_mbps' : args.bw,
        'delay'   : args.delay,
        'tests'   : {},
    }

    try:
        net = build_net(bw=args.bw, delay=args.delay)
        net.start()

        info('[*] Waiting for controller handshake (5s)...\n')
        time.sleep(5)

        info('[*] Connectivity check:\n')
        loss = net.pingAll(timeout=3)
        all_results['ping_loss_pct'] = loss

        if args.scenario in ('sequential', 'all'):
            all_results['tests']['sequential'] = scenario_sequential(net)
        if args.scenario in ('simultaneous', 'all'):
            all_results['tests']['simultaneous'] = scenario_simultaneous(net)
        if args.scenario in ('firewall', 'all'):
            all_results['tests']['firewall'] = scenario_firewall(net)
        if args.scenario in ('qos', 'all'):
            all_results['tests']['qos'] = scenario_qos(net)

        dump = dump_flows(net)
        info('\n[*] Flow table (s1):\n' + dump + '\n')
        all_results['flow_table_dump'] = dump

        if args.cli:
            CLI(net)

    finally:
        if net is not None:
            net.stop()

    out = os.path.join(RESULTS_DIR, 'topology2_star_results.json')
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    info(f'[*] Results saved -> {out}\n')

if __name__ == '__main__':
    main()
