"""Two physically separate paths between clients and UDP server."""
from mininet.topo import Topo


class AdaptiveTopo(Topo):
    def build(self):
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13", failMode="secure")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13", failMode="secure")
        s3 = self.addSwitch("s3", dpid="0000000000000003", protocols="OpenFlow13", failMode="secure")
        s4 = self.addSwitch("s4", dpid="0000000000000004", protocols="OpenFlow13", failMode="secure")

        self.addLink(h1, s1, port2=1)
        self.addLink(h3, s1, port2=4)
        self.addLink(s1, s2, port1=2, port2=1)
        self.addLink(s2, s4, port1=2, port2=1)
        self.addLink(s1, s3, port1=3, port2=1)
        self.addLink(s3, s4, port1=2, port2=2)
        self.addLink(s4, h2, port1=3)


topos = {"adaptive": lambda: AdaptiveTopo()}
