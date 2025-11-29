#!/usr/bin/env python3

from mininet.topo import Topo

class LoopFreeTopo(Topo):
    """Loop-free topology for initial testing"""
    def __init__(self):
        Topo.__init__(self)
        
        # Add 6 switches
        switches = []
        for i in range(1, 7):
            switches.append(self.addSwitch('s%s' % i))
        
        # Add 6 hosts
        hosts = []
        for i in range(1, 7):
            hosts.append(self.addHost('h%s' % i, ip='10.0.0.%s/24' % i))
        
        # Create a tree topology (loop-free)
        # Core switches
        self.addLink(switches[0], switches[1])  # S1-S2
        self.addLink(switches[0], switches[2])  # S1-S3
        self.addLink(switches[1], switches[3])  # S2-S4
        self.addLink(switches[1], switches[4])  # S2-S5
        self.addLink(switches[2], switches[5])  # S3-S6
        
        # Connect hosts to switches
        self.addLink(hosts[0], switches[0])  # H1-S1
        self.addLink(hosts[1], switches[1])  # H2-S2
        self.addLink(hosts[2], switches[2])  # H3-S3
        self.addLink(hosts[3], switches[3])  # H4-S4
        self.addLink(hosts[4], switches[4])  # H5-S5
        self.addLink(hosts[5], switches[5])  # H6-S6

class ProjectTopo(Topo):
    """Original project topology with loops - for advanced testing"""
    def __init__(self):
        Topo.__init__(self)
        
        # Add 6 switches
        switches = []
        for i in range(1, 7):
            switches.append(self.addSwitch('s%s' % i))
        
        # Add 6 hosts
        hosts = []
        for i in range(1, 7):
            hosts.append(self.addHost('h%s' % i, ip='10.0.0.%s/24' % i))
        
        # Create network connections (as per project diagram)
        self.addLink(switches[0], switches[1])  # S1-S2
        self.addLink(switches[1], switches[2])  # S2-S3
        self.addLink(switches[0], switches[3])  # S1-S4
        self.addLink(switches[3], switches[4])  # S4-S5
        self.addLink(switches[4], switches[5])  # S5-S6
        self.addLink(switches[3], switches[5])  # S4-S6
        self.addLink(switches[1], switches[4])  # S2-S5
        self.addLink(switches[2], switches[5])  # S3-S6
        
        # Connect hosts to switches
        for i in range(6):
            self.addLink(hosts[i], switches[i])

# Register both topologies
topos = {
    'loopfree': (lambda: LoopFreeTopo()),
    'projecttopo': (lambda: ProjectTopo())
}
