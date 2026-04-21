#!/usr/bin/env python3
"""
Scenario 3: QoS-style rate limiting check.

Rate limiting is applied at host interfaces using Linux tc:
- h3 limited to ~2 Mbps
- h4 limited to ~5 Mbps
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

def run_iperf3(client, server_ip, label, duration=5):
    # Use JSON mode so Mbps can be parsed reliably.
    raw = client.cmd(f'iperf3 -c {server_ip} -t {duration} -J')
    result = {'label': label, 'Mbps': 0.0}
    try:
        # Extract only JSON because extra shell text can appear in output.
        start = raw.find('{')
        end_idx = raw.rfind('}')
        if start != -1 and end_idx != -1:
            clean_json = raw[start:end_idx+1]
            data = json.loads(clean_json)
            end_data = data.get('end', {})
            
            if 'sum_received' in end_data:
                mbps = end_data['sum_received'].get('bits_per_second', 0) / 1e6
            elif 'sum_sent' in end_data:
                mbps = end_data['sum_sent'].get('bits_per_second', 0) / 1e6
            else:
                mbps = 0.0
            result['Mbps'] = round(mbps, 3)
    except:
        pass
    return result

def main():
    setLogLevel('info')

    # Standalone setup keeps this scenario focused on interface shaping.
    net = Mininet(switch=OVSSwitch, link=TCLink, controller=None, autoSetMacs=True)
    s1 = net.addSwitch('s1', failMode='standalone')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    for h in (h1, h2, h3, h4): net.addLink(h, s1, bw=100, delay='2ms')
    
    results = {'scenario': 'qos', 'tests': {}}
    try:
        net.start()
        time.sleep(2)
        net.pingAll(timeout=1)

        # Queue limit keeps TCP stable under low-rate shaping.
        h3.cmd('tc qdisc add dev h3-eth0 root tbf rate 2mbit burst 200kb limit 200000')
        h4.cmd('tc qdisc add dev h4-eth0 root tbf rate 5mbit burst 200kb limit 200000')
        
        # Compare one unlimited host with two limited hosts.
        h1.cmd('iperf3 -s -D')
        results['tests']['unlimited_h2'] = run_iperf3(h2, h1.IP(), 'h2->h1 Unlimited')
        results['tests']['limited_h3'] = run_iperf3(h3, h1.IP(), 'h3->h1 QoS 2Mbps')
        results['tests']['limited_h4'] = run_iperf3(h4, h1.IP(), 'h4->h1 QoS 5Mbps')
        h1.cmd('pkill -9 -f iperf3')
    finally:
        net.stop()
        
    # Save output for analysis graphs and final report table.
    with open(os.path.join(RESULTS_DIR, 'scenario3_qos.json'), 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
