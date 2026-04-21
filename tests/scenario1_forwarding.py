#!/usr/bin/env python3
"""
Scenario 1: Basic forwarding and throughput checks on a linear topology.

This script keeps the setup simple:
- h1 <-> s1 <-> h2
- standalone OVS switch
- iperf3 JSON output stored in results/scenario1_forwarding.json
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
from mininet.log  import setLogLevel

RESULTS_DIR = os.path.join(PROJECT_DIR, 'results')

def run_iperf3(client, server_ip, label, duration=5, parallel=1, udp=False):
    # Build an iperf3 command that always returns JSON output.
    cmd = f'iperf3 -c {server_ip} -t {duration} -J'
    if parallel > 1: cmd += f' -P {parallel}'
    if udp: cmd += ' -u -b 100M'
    
    raw = client.cmd(cmd)
    result = {'label': label, 'summary': {'Mbps': 0.0}}
    
    try:
        # In Mininet runs, extra shell text can appear around JSON.
        # Extract only the JSON part before parsing.
        start = raw.find('{')
        end_idx = raw.rfind('}')
        if start != -1 and end_idx != -1:
            clean_json = raw[start:end_idx+1]
            data = json.loads(clean_json)
            end_data = data.get('end', {})
            
            if udp:
                mbps = end_data.get('sum', {}).get('bits_per_second', 0) / 1e6
            else:
                # TCP summary key can vary with iperf mode/version.
                if 'sum_received' in end_data:
                    mbps = end_data['sum_received'].get('bits_per_second', 0) / 1e6
                elif 'sum_sent' in end_data:
                    mbps = end_data['sum_sent'].get('bits_per_second', 0) / 1e6
                elif 'streams' in end_data and len(end_data['streams']) > 0:
                    mbps = end_data['streams'][0].get('receiver', {}).get('bits_per_second', 0) / 1e6
                else:
                    mbps = 0.0
                    
            result['summary']['Mbps'] = round(mbps, 3)
    except:
        pass
        
    return result

def main():
    setLogLevel('info')
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Standalone switch mode is enough for this baseline throughput scenario.
    net = Mininet(switch=OVSSwitch, link=TCLink, controller=None, autoSetMacs=True)
    s1 = net.addSwitch('s1', failMode='standalone')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    net.addLink(h1, s1, bw=100, delay='5ms')
    net.addLink(h2, s1, bw=100, delay='5ms')
    
    results = {'scenario': 'forwarding', 'tests': {}}
    try:
        net.start()
        time.sleep(2)

        # Warm-up ping helps populate ARP entries before iperf.
        net.pingAll(timeout=1)
        
        # Run h1 as server and h2 as client for all three checks.
        h1.cmd('iperf3 -s -D')
        results['tests']['tcp_baseline'] = run_iperf3(h2, h1.IP(), 'TCP Baseline')
        results['tests']['udp_baseline'] = run_iperf3(h2, h1.IP(), 'UDP Baseline', udp=True)
        results['tests']['tcp_parallel'] = run_iperf3(h2, h1.IP(), 'TCP 4 Streams', parallel=4)
        h1.cmd('pkill -9 -f iperf3')
    finally:
        net.stop()
        
    # Save output for analysis/analyze_results.py.
    with open(os.path.join(RESULTS_DIR, 'scenario1_forwarding.json'), 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
