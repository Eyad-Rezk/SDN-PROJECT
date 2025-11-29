#!/usr/bin/env python3

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpidToStr
from pox.lib.packet.ethernet import ethernet
from pox.lib.packet.ipv4 import ipv4
import time
import json

log = core.getLogger()

class LoadBalancerController:
    def __init__(self):
        self.monitoring_interval = 5  # seconds
        self.congestion_threshold = 0.7  # 70% utilization
        self.switch_stats = {}
        self.flow_counters = {}
        self.mac_to_port = {}  # MAC learning table
        
        # Register for OpenFlow connection events
        core.openflow.addListeners(self)
        log.info("Load Balancer Controller started")
    
    def _handle_ConnectionUp(self, event):
        """When a switch connects"""
        dpid = dpidToStr(event.dpid)
        log.info("Switch %s connected", dpid)
        self.switch_stats[dpid] = {}
        self.mac_to_port[dpid] = {}
        
        # Start periodic statistics collection
        self._request_stats(event)
    
    def _handle_PacketIn(self, event):
        """Handle packets when no flow rule exists"""
        packet = event.parsed
        if not packet.parsed:
            log.warning("Ignoring incomplete packet")
            return

        dpid = dpidToStr(event.connection.dpid)
        in_port = event.port
        
        # Learn the source MAC address
        self.mac_to_port[dpid][packet.src] = in_port
        
        # If we know the destination, flood to all ports except input port
        if packet.dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][packet.dst]
            log.debug("Installing flow from %s to %s on switch %s port %d", 
                     packet.src, packet.dst, dpid, out_port)
        else:
            out_port = of.OFPP_FLOOD
            log.debug("Flooding packet from %s on switch %s", packet.src, dpid)
        
        # Install flow rule
        self._install_flow(event.connection, event.ofp, in_port, out_port, packet)
    
    def _install_flow(self, connection, ofp, in_port, out_port, packet):
        """Install a flow rule in the switch"""
        msg = of.ofp_flow_mod()
        msg.match = of.ofp_match.from_packet(packet, in_port)
        msg.actions.append(of.ofp_action_output(port=out_port))
        msg.idle_timeout = 10
        msg.hard_timeout = 30
        connection.send(msg)
        
        # Also send the packet that triggered this
        if out_port != of.OFPP_FLOOD:
            self._send_packet(connection, ofp, out_port, packet)
    
    def _send_packet(self, connection, ofp, out_port, packet):
        """Send a single packet out the specified port"""
        msg = of.ofp_packet_out()
        msg.data = ofp.data
        msg.actions.append(of.ofp_action_output(port=out_port))
        msg.in_port = ofp.in_port
        connection.send(msg)
    
    def _request_stats(self, event=None):
        """Request port statistics from all switches"""
        if event is None:
            # This is the periodic call
            for connection in core.openflow._connections.values():
                self._request_stats_for_connection(connection)
        else:
            self._request_stats_for_connection(event.connection)
        
        # Schedule next statistics collection
        core.callLater(self.monitoring_interval, self._request_stats)
    
    def _request_stats_for_connection(self, connection):
        """Request stats for a specific switch connection"""
        msg = of.ofp_stats_request()
        msg.body = of.ofp_port_stats_request()
        connection.send(msg)
    
    def _handle_PortStatsReceived(self, event):
        """Handle received port statistics"""
        dpid = dpidToStr(event.connection.dpid)
        
        for stat in event.stats:
            port_no = stat.port_no
            if port_no >= of.OFPP_MAX:  # Skip reserved ports
                continue
                
            # Calculate utilization
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes
            
            # Store current stats
            port_key = f"{dpid}-{port_no}"
            if port_key not in self.flow_counters:
                self.flow_counters[port_key] = {
                    'prev_rx': rx_bytes,
                    'prev_tx': tx_bytes,
                    'current_rx': rx_bytes,
                    'current_tx': tx_bytes
                }
            else:
                # Update counters and calculate usage
                self.flow_counters[port_key]['prev_rx'] = self.flow_counters[port_key]['current_rx']
                self.flow_counters[port_key]['prev_tx'] = self.flow_counters[port_key]['current_tx']
                self.flow_counters[port_key]['current_rx'] = rx_bytes
                self.flow_counters[port_key]['current_tx'] = tx_bytes
            
            # Calculate bandwidth usage (bytes per second)
            time_interval = self.monitoring_interval
            rx_usage = (rx_bytes - self.flow_counters[port_key]['prev_rx']) / time_interval
            tx_usage = (tx_bytes - self.flow_counters[port_key]['prev_tx']) / time_interval
            
            # Log the statistics (reduce verbosity for now)
            if rx_usage > 1000 or tx_usage > 1000:  # Only log if there's significant traffic
                log.info("Switch %s Port %d: RX=%d B/s, TX=%d B/s", 
                        dpid, port_no, rx_usage, tx_usage)
            
            # Check for congestion
            total_usage = rx_usage + tx_usage
            if total_usage > 1000000:  # 1 MB/s threshold for demo
                log.warning("⚠️  Potential congestion on %s port %d: %d bytes/s", 
                           dpid, port_no, total_usage)

def launch():
    """Start the Load Balancer Controller"""
    core.registerNew(LoadBalancerController)
