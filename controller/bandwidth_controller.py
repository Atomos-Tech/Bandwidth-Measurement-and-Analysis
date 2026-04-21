"""
=============================================================================
 Bandwidth Measurement and Analysis — SDN Controller
 Ryu + OpenFlow 1.3
=============================================================================

 Features:
   1. L2 MAC-Learning Switch  — packet_in → match+action flow_mod
   2. Firewall (DROP rules)   — high-priority static rules
   3. QoS Meter Bands         — per-host rate limiting in kbps
   4. Statistics Collection   — periodic flow/port stats → JSON

 Usage:
   ryu-manager controller/bandwidth_controller.py [--firewall] [--qos]

 Flow table priority scheme:
   Priority 200  —  Firewall DROP (src/dst IP + TCP port)
   Priority 150  —  QoS meter (src IP → meter → NORMAL)
   Priority  10  —  L2 unicast (learned MAC → output port)
   Priority   0  —  Table-miss → CONTROLLER

=============================================================================
"""

import json
import os
import sys
import time
import logging

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                     DEAD_DISPATCHER, set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4
from ryu.lib import hub

LOG = logging.getLogger('bandwidth_controller')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s  %(message)s',
    datefmt='%H:%M:%S',
)

STATS_DIR  = '/tmp/sdn_results'
STATS_FILE = os.path.join(STATS_DIR, 'flow_stats.json')


class BandwidthController(app_manager.RyuApp):
    """
    SDN controller demonstrating:
      - L2 learning switch (reactive flow installation from packet_in)
      - Firewall (proactive DROP rules installed at switch connect)
      - QoS rate limiting (OpenFlow meter bands)
      - Continuous statistics collection (background thread)
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # ------------------------------------------------------------------
    #  Firewall rules — installed at switch connect when --firewall flag
    # ------------------------------------------------------------------
    FIREWALL_RULES = [
        {
            'src_ip'  : '10.0.0.3',
            'dst_ip'  : '10.0.0.1',
            'proto'   : 'tcp',
            'dst_port': 5201,
            'priority': 200,
            'desc'    : 'Block iperf3 TCP  h3 -> h1',
        },
        {
            'src_ip'  : '10.0.0.1',
            'dst_ip'  : '10.0.0.3',
            'proto'   : 'tcp',
            'src_port': 5201,
            'priority': 200,
            'desc'    : 'Block iperf3 reply  h1 -> h3',
        },
    ]

    # ------------------------------------------------------------------
    #  QoS meters — meter_id -> rate in kbps
    # ------------------------------------------------------------------
    QOS_METERS = {
        1: 2000,   # 2 Mbps for h3  (10.0.0.3)
        2: 5000,   # 5 Mbps for h4  (10.0.0.4)
    }

    # IP -> meter_id mapping (used when --qos flag is set)
    QOS_IP_MAP = {
        '10.0.0.3': 1,
        '10.0.0.4': 2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}   # {dpid: {mac: port}}
        self.datapaths   = {}   # {dpid: datapath}
        self.flow_stats  = {}   # {dpid: [snapshot, ...]}
        self.flow_log    = []   # install log

        # Parse CLI flags — Ryu passes its own args so we check sys.argv
        self.enable_firewall = '--firewall' in sys.argv
        self.enable_qos      = '--qos'      in sys.argv

        os.makedirs(STATS_DIR, exist_ok=True)

        # Start background statistics monitor
        self._monitor_thread = hub.spawn(self._monitor_loop)

        LOG.info('=' * 60)
        LOG.info(' BandwidthController started  (OpenFlow 1.3)')
        LOG.info(' Firewall : %s', 'ON  (--firewall)' if self.enable_firewall else 'OFF')
        LOG.info(' QoS      : %s', 'ON  (--qos)'      if self.enable_qos      else 'OFF')
        LOG.info('=' * 60)

    # ==================================================================
    #  Switch lifecycle
    # ==================================================================

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features_handler(self, ev):
        """
        Called once when a switch connects.
        Install: table-miss, QoS meters, firewall DROP rules (if enabled).
        """
        dp   = ev.msg.datapath
        dpid = dp.id
        self.datapaths[dpid] = dp
        self.mac_to_port.setdefault(dpid, {})

        LOG.info('[Switch %016x] Connected', dpid)

        self._install_table_miss(dp)
        self._install_meters(dp)

        if self.enable_firewall:
            self._install_firewall_rules(dp)

        if self.enable_qos:
            for ip, meter_id in self.QOS_IP_MAP.items():
                self._install_qos_flow(dp, ip, meter_id)

        LOG.info('[Switch %016x] Ready', dpid)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths.setdefault(dp.id, dp)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)
            LOG.info('[Switch %016x] Disconnected', dp.id)

    # ==================================================================
    #  Table-miss rule
    # ==================================================================

    def _install_table_miss(self, dp):
        """Priority 0 catch-all: send to controller."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, priority=0, match=match, instructions=inst))
        LOG.info('[Switch %016x] table-miss installed', dp.id)

    # ==================================================================
    #  Firewall
    # ==================================================================

    def _install_firewall_rules(self, dp):
        """Install permanent DROP rules at priority 200."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        PROTO  = {'tcp': 6, 'udp': 17, 'icmp': 1}

        for rule in self.FIREWALL_RULES:
            fields = {'eth_type': ether_types.ETH_TYPE_IP}
            if 'src_ip'   in rule: fields['ipv4_src'] = rule['src_ip']
            if 'dst_ip'   in rule: fields['ipv4_dst'] = rule['dst_ip']

            pname = rule.get('proto')
            if pname:
                fields['ip_proto'] = PROTO[pname]
                if 'dst_port' in rule:
                    fields[f'{pname}_dst'] = rule['dst_port']
                if 'src_port' in rule:
                    fields[f'{pname}_src'] = rule['src_port']

            match = parser.OFPMatch(**fields)
            # Empty action list = DROP
            inst  = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, [])]
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp,
                priority=rule.get('priority', 200),
                match=match,
                instructions=inst,
                idle_timeout=0,
                hard_timeout=0,
            ))
            LOG.info('[Firewall] DROP: %s', rule.get('desc', str(rule)))

    # ==================================================================
    #  QoS meters
    # ==================================================================

    def _install_meters(self, dp):
        """Install OFP meter bands (always provisioned, rules optional)."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        for meter_id, rate_kbps in self.QOS_METERS.items():
            burst = max(rate_kbps // 10, 64)
            bands = [parser.OFPMeterBandDrop(rate=rate_kbps,
                                             burst_size=burst)]
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp,
                command=ofp.OFPMC_ADD,
                flags=ofp.OFPMF_KBPS,
                meter_id=meter_id,
                bands=bands,
            ))
            LOG.info('[Meter %d] %d kbps drop band installed', meter_id, rate_kbps)

    def _install_qos_flow(self, dp, src_ip, meter_id):
        """Flow rule: traffic from src_ip → apply meter → NORMAL output."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        match  = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=src_ip,
        )
        inst = [
            parser.OFPInstructionMeter(meter_id, ofp.OFPIT_METER),
            parser.OFPInstructionActions(
                ofp.OFPIT_APPLY_ACTIONS,
                [parser.OFPActionOutput(ofp.OFPP_NORMAL)],
            ),
        ]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            priority=150,
            match=match,
            instructions=inst,
            idle_timeout=0,
            hard_timeout=0,
        ))
        LOG.info('[QoS] %s -> meter %d (%d kbps)',
                 src_ip, meter_id, self.QOS_METERS[meter_id])

    # ==================================================================
    #  Packet-in handler — MAC learning + reactive flow installation
    # ==================================================================

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
        Core SDN logic (reactive):
          1. Parse packet, skip LLDP
          2. Learn src_mac -> in_port
          3. Look up dst_mac
          4. Install unicast flow rule if dst known
          5. Forward packet
        """
        msg     = ev.msg
        dp      = msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        in_port = msg.match['in_port']
        dpid    = dp.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Skip LLDP and STP
        if eth.ethertype in (ether_types.ETH_TYPE_LLDP, 0x8942):
            return

        dst = eth.dst
        src = eth.src

        # 1. MAC learning
        tbl = self.mac_to_port.setdefault(dpid, {})
        if src not in tbl:
            LOG.info('[Switch %016x] Learn %s -> port %d', dpid, src, in_port)
        tbl[src] = in_port

        # 2. Determine output port
        out_port = tbl.get(dst, ofp.OFPP_FLOOD)
        actions  = [parser.OFPActionOutput(out_port)]

        # 3. Install unicast flow rule
        if out_port != ofp.OFPP_FLOOD:
            # Detect protocol for logging
            ip_pkt  = pkt.get_protocol(ipv4.ipv4)
            proto_s = 'L2'
            if ip_pkt:
                proto_s = {1: 'ICMP', 6: 'TCP', 17: 'UDP'}.get(
                    ip_pkt.proto, str(ip_pkt.proto))

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst,
                eth_src=src,
            )
            self._send_flow_mod(
                dp, match, actions,
                priority=10,
                idle_timeout=30,
                hard_timeout=120,
            )
            self.flow_log.append({
                'ts'     : time.strftime('%H:%M:%S'),
                'dpid'   : format(dpid, '016x'),
                'src'    : src,
                'dst'    : dst,
                'port'   : out_port,
                'proto'  : proto_s,
            })
            LOG.info('[Switch %016x] Flow %s->%s port %d [%s]',
                     dpid, src, dst, out_port, proto_s)

        # 4. Forward the buffered packet
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        ))

    # ==================================================================
    #  Flow rule helper
    # ==================================================================

    def _send_flow_mod(self, dp, match, actions, priority=1,
                       idle_timeout=0, hard_timeout=0):
        """Send an OFPFlowMod to the switch."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        ))

    # ==================================================================
    #  Statistics collection (background thread)
    # ==================================================================

    def _monitor_loop(self):
        """Request flow and port stats from every switch every 10 s."""
        LOG.info('[Monitor] Started (10s interval)')
        while True:
            for dp in list(self.datapaths.values()):
                dp.send_msg(dp.ofproto_parser.OFPFlowStatsRequest(dp))
                dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(
                    dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(10)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        ts   = time.time()

        snapshot = {
            'timestamp': ts,
            'time_str' : time.strftime('%H:%M:%S', time.localtime(ts)),
            'dpid'     : format(dpid, '016x'),
            'flows'    : [],
        }

        LOG.info('\n  Flow Table  Switch %016x  @ %s', dpid, snapshot['time_str'])
        LOG.info('  %5s %4s %10s %13s  Match', 'Pri', 'Tbl', 'Pkts', 'Bytes')

        for stat in sorted(body, key=lambda s: s.priority, reverse=True):
            LOG.info('  %5d %4d %10d %13d  %s',
                     stat.priority, stat.table_id,
                     stat.packet_count, stat.byte_count, stat.match)
            snapshot['flows'].append({
                'priority'    : stat.priority,
                'table_id'    : stat.table_id,
                'packet_count': stat.packet_count,
                'byte_count'  : stat.byte_count,
                'duration_sec': stat.duration_sec,
                'idle_timeout': stat.idle_timeout,
                'hard_timeout': stat.hard_timeout,
                'match'       : str(stat.match),
            })

        self.flow_stats.setdefault(format(dpid, '016x'), []).append(snapshot)
        self._save_stats()

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        LOG.info('\n  Port Stats  Switch %016x', dpid)
        for p in body:
            if p.port_no < 0xFFFFFF00:
                LOG.info('  port %3d  rx %10d pkts  tx %10d pkts  '
                         'rx %12d B  tx %12d B',
                         p.port_no, p.rx_packets, p.tx_packets,
                         p.rx_bytes, p.tx_bytes)

    def _save_stats(self):
        try:
            with open(STATS_FILE, 'w') as f:
                json.dump({
                    'flow_stats': self.flow_stats,
                    'flow_log'  : self.flow_log,
                    'saved_at'  : time.strftime('%Y-%m-%dT%H:%M:%S'),
                }, f, indent=2, default=str)
        except Exception as exc:
            LOG.warning('[Stats] Save failed: %s', exc)
