#!/usr/bin/env python3
"""
Scenario 2: Firewall behavior check.

Goal:
- allow h2 -> h1 TCP traffic
- block h3 -> h1 TCP traffic on port 5201
"""

import os
import sys
import json
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from mininet.net  import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from mininet.log  import setLogLevel, info

RESULTS_DIR = os.path.join(PROJECT_DIR, 'results')

def run_iperf3_test(client, server_ip, label, duration=5):
    # Small timeout keeps blocked-flow test fast and deterministic.
    raw = client.cmd(f'iperf3 -c {server_ip} -t {duration} -J --connect-timeout 2000')
    result = {'label': label, 'status': 'unknown'}
    try:
        data = json.loads(raw)
        mbps = (data.get('end', {}).get('sum_received') or data.get('end', {}).get('streams', [{}])[0].get('receiver', {})).get('bits_per_second', 0) / 1e6
        # Near-zero throughput is treated as blocked in this test.
        result['status'] = 'blocked' if mbps < 0.01 else 'allowed'
        result['Mbps'] = round(mbps, 3)
    except:
        # Parse failure usually means connection could not be established.
        result['status'] = 'blocked'
        result['Mbps'] = 0.00
    return result

def main():
    setLogLevel('info')

    # Standalone switch for controlled rule injection with ovs-ofctl.
    net = Mininet(switch=OVSSwitch, link=TCLink, controller=None, autoSetMacs=True)
    s1 = net.addSwitch('s1', failMode='standalone')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    for h in (h1, h2, h3): net.addLink(h, s1, bw=100, delay='2ms')
    
    results = {'scenario': 'firewall', 'tests': {}}
    try:
        net.start()
        time.sleep(2)
        net.pingAll(timeout=1)

        # Inject one explicit DROP rule for h3 -> h1 iperf flow.
        s1.cmd('ovs-ofctl add-flow s1 "priority=200,tcp,nw_src=10.0.0.3,nw_dst=10.0.0.1,tp_dst=5201,actions=drop"')
        
        # h1 runs server; h2 should pass and h3 should be blocked.
        h1.cmd('iperf3 -s -p 5201 -D')
        results['tests']['allowed_h2_to_h1'] = run_iperf3_test(h2, h1.IP(), 'h2->h1 TCP')
        results['tests']['blocked_h3_to_h1'] = run_iperf3_test(h3, h1.IP(), 'h3->h1 TCP')
        h1.cmd('pkill -9 -f iperf3')
    finally:
        net.stop()
        
    # Save output for report and plotting scripts.
    with open(os.path.join(RESULTS_DIR, 'scenario2_firewall.json'), 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
