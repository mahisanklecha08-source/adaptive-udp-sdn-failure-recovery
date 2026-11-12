"""Ryu OpenFlow 1.3 controller for the fixed Mininet diamond.

Run with ADAPTIVE_MODE=dynamic (default) or ADAPTIVE_MODE=static.
"""
import os

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

from routing import CLIENTS, LINKS, SERVER_IP, SWITCH_PORTS, choose_path, edge, forwarding_ports


COOKIE = 0xADAD30
COOKIE_MASK = 0xFFFFFFFFFFFFFFFF
POLL_SECONDS = 0.5


class AdaptiveController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = os.environ.get("ADAPTIVE_MODE", "dynamic").lower()
        if self.mode not in ("dynamic", "static"):
            raise ValueError("ADAPTIVE_MODE must be dynamic or static")
        self.datapaths = {}
        self.port_down = {}
        self.path = None
        self.logger.info("controller mode=%s; primary=s1-s2-s4; backup=s1-s3-s4", self.mode)
        self.monitor_thread = hub.spawn(self._monitor)

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                dp.send_msg(dp.ofproto_parser.OFPPortDescStatsRequest(dp, 0))
            hub.sleep(POLL_SECONDS)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def switch_state(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info("switch s%s connected", dp.id)
            self._reprogram(force=True)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)
            self.logger.warning("switch s%s disconnected", dp.id)
            self._reprogram()

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status(self, ev):
        msg = ev.msg
        self._record_port(msg.datapath, msg.desc, msg.reason == msg.datapath.ofproto.OFPPR_DELETE)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_descriptions(self, ev):
        for desc in ev.msg.body:
            self._record_port(ev.msg.datapath, desc, False)

    def _record_port(self, dp, desc, deleted):
        known_ports = {(switch, port) for (switch, _peer), port in SWITCH_PORTS.items()}
        if (dp.id, desc.port_no) not in known_ports:
            return
        ofp = dp.ofproto
        down = deleted or bool(desc.config & ofp.OFPPC_PORT_DOWN) or bool(desc.state & ofp.OFPPS_LINK_DOWN)
        key = (dp.id, desc.port_no)
        if self.port_down.get(key) != down:
            self.port_down[key] = down
            self.logger.info("s%s port %s %s", dp.id, desc.port_no, "DOWN" if down else "UP")
            self._reprogram()

    def _failed_links(self):
        return {edge(a, b) for a, b in LINKS
                if self.port_down.get((a, SWITCH_PORTS[(a, b)]), False)
                or self.port_down.get((b, SWITCH_PORTS[(b, a)]), False)}

    def _desired_path(self):
        active = set(self.datapaths)
        if self.mode == "static":
            return (1, 2, 4) if {1, 2, 4} <= active else None
        return choose_path(self._failed_links(), active)

    def _delete_managed_flows(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, cookie=COOKIE, cookie_mask=COOKIE_MASK,
            table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
            match=parser.OFPMatch()))

    def _add_flow(self, dp, src, dst, out_port):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src, ipv4_dst=dst)
        actions = [parser.OFPActionOutput(out_port)]
        instructions = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, cookie=COOKIE, table_id=0, command=ofp.OFPFC_ADD,
            priority=100, match=match, instructions=instructions))

    def _reprogram(self, force=False):
        desired = self._desired_path()
        if desired == self.path and not force:
            return
        for dp in self.datapaths.values():
            self._delete_managed_flows(dp)
        if desired:
            for client_ip, client_port in CLIENTS.items():
                forward, reverse = forwarding_ports(desired, client_port)
                for switch in desired:
                    dp = self.datapaths[switch]
                    self._add_flow(dp, client_ip, SERVER_IP, forward[switch])
                    self._add_flow(dp, SERVER_IP, client_ip, reverse[switch])
        self.path = desired
        self.logger.warning("active path: %s; failed links: %s",
                            "-".join("s%s" % node for node in desired) if desired else "NONE",
                            sorted(self._failed_links()))
