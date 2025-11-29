#!/usr/bin/env python3

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpidToStr
from pox.lib.packet.ethernet import ethernet
from pox.lib.packet.arp import arp
import time

log = core.getLogger()

class SimpleLoadBalancer:
    def __init__(self):
        self.monitoring_interval = 5
        self.congestion_threshold = 0.7
        
        # MAC learning table: {dpid: {mac: port}}
        self.mac_table = {}
        
        # Statistics
        self.flow_counters = {}
        self.congested_links = set()
        
        core.openflow.addListeners(self)
        log.info("Simple Load Balancer Controller started")
    
    def _handle_ConnectionUp(self, event):
        """When a switch connects"""
        dpid = dpidToStr(event.dpid)
        log.info("Switch %s connected", dpid)
        self.mac_table[dpid] = {}
        
        # Install table-miss flow entry to send packets to controller
        msg = of.ofp_flow_mod()
        msg.priority = 0  # Lowest priority
        msg.actions.append(of.ofp_action_output(port=of.OFPP_CONTROLLER))
        event.connection.send(msg)
        
        log.debug("Installed table-miss flow on switch %s", dpid)
        
        # Start statistics collection for this switch
        self._request_stats(event.connection)
    
    def _request_stats(self, connection=None):
        """Request port statistics from switches"""
        if connection is None:
            # Periodic call - request from all switches
            for conn in core.openflow._connections.values():
                self._request_stats_for_connection(conn)
        else:
            # Initial call for a specific switch
            self._request_stats_for_connection(connection)
        
        # Schedule next collection
        core.callLater(self.monitoring_interval, self._request_stats)
    
    def _request_stats_for_connection(self, connection):
        """Request stats for a specific switch connection"""
        msg = of.ofp_stats_request()
        msg.body = of.ofp_port_stats_request()
        connection.send(msg)
    
    def _handle_PacketIn(self, event):
        """Handle incoming packets"""
        packet = event.parsed
        if not packet.parsed:
            log.warning("Unparsed packet from switch %s", dpidToStr(event.connection.dpid))
            return

        dpid = dpidToStr(event.connection.dpid)
        in_port = event.port
        
        # Learn source MAC address
        if packet.src not in self.mac_table[dpid]:
            self.mac_table[dpid][packet.src] = in_port
            log.info("Learned %s on switch %s port %d", packet.src, dpid, in_port)
        
        # Handle different packet types
        if packet.type == packet.LLDP_TYPE or packet.type == packet.IPV6_TYPE:
            # Ignore LLDP and IPv6 packets for now
            return
        elif packet.type == packet.ARP_TYPE:
            self._handle_arp(event, packet, dpid, in_port)
        else:
            self._handle_other_packet(event, packet, dpid, in_port)
    
    def _handle_arp(self, event, packet, dpid, in_port):
        """Handle ARP packets by flooding"""
        log.debug("Flooding ARP packet on switch %s", dpid)
        self._flood_packet(event)
    
    def _handle_other_packet(self, event, packet, dpid, in_port):
        """Handle other packet types (IP, etc.)"""
        # Check if we know the destination MAC
        if packet.dst in self.mac_table[dpid]:
            out_port = self.mac_table[dpid][packet.dst]
            log.debug("Forwarding %s -> %s on switch %s port %d", 
                     packet.src, packet.dst, dpid, out_port)
            self._install_flow(event.connection, packet, in_port, out_port)
            self._send_packet(event, out_port)
        else:
            log.debug("Flooding packet from %s on switch %s", packet.src, dpid)
            self._flood_packet(event)
    
    def _install_flow(self, connection, packet, in_port, out_port):
        """Install a flow rule"""
        msg = of.ofp_flow_mod()
        msg.match = of.ofp_match.from_packet(packet, in_port)
        msg.actions.append(of.ofp_action_output(port=out_port))
        msg.idle_timeout = 10
        msg.hard_timeout = 30
        connection.send(msg)
        
        log.debug("Installed flow: %s in_port:%d -> out_port:%d", 
                 dpidToStr(connection.dpid), in_port, out_port)
    
    def _send_packet(self, event, out_port):
        """Send a single packet"""
        msg = of.ofp_packet_out()
        msg.data = event.ofp
        msg.actions.append(of.ofp_action_output(port=out_port))
        msg.in_port = event.port
        event.connection.send(msg)
    
    def _flood_packet(self, event):
        """Flood packet to all ports except input port"""
        msg = of.ofp_packet_out()
        msg.data = event.ofp
        msg.actions.append(of.ofp_action_output(port=of.OFPP_FLOOD))
        msg.in_port = event.port
        event.connection.send(msg)
    
    def _handle_PortStatsReceived(self, event):
        """Handle port statistics"""
        dpid = dpidToStr(event.connection.dpid)
        
        for stat in event.stats:
            if stat.port_no >= of.OFPP_MAX:
                continue
                
            self._update_link_stats(dpid, stat.port_no, stat)
    
    def _update_link_stats(self, dpid, port, stat):
        """Update and analyze link statistics"""
        port_key = f"{dpid}-{port}"
        current_time = time.time()
        
        if port_key not in self.flow_counters:
            self.flow_counters[port_key] = {
                'prev_rx': stat.rx_bytes,
                'prev_tx': stat.tx_bytes,
                'prev_time': current_time,
                'utilization': 0
            }
            return
        
        # Calculate data rate
        time_diff = current_time - self.flow_counters[port_key]['prev_time']
        if time_diff > 0:
            rx_rate = (stat.rx_bytes - self.flow_counters[port_key]['prev_rx']) / time_diff
            tx_rate = (stat.tx_bytes - self.flow_counters[port_key]['prev_tx']) / time_diff
            
            # Assume 100 Mbps link capacity
            link_capacity = 100 * 1024 * 1024 / 8  # bytes per second
            utilization = (rx_rate + tx_rate) / link_capacity
            
            # Update counters
            self.flow_counters[port_key].update({
                'prev_rx': stat.rx_bytes,
                'prev_tx': stat.tx_bytes,
                'prev_time': current_time,
                'utilization': utilization
            })
            
            # Log significant utilization
            if utilization > 0.05:  # Only log if > 5% utilization
                log.info("📊 %s port %d: %.1f%% util", dpid, port, utilization * 100)
            
            # Check for congestion
            if utilization > self.congestion_threshold:
                if port_key not in self.congested_links:
                    log.warning("🚨 CONGESTION on %s port %d: %.1f%%", 
                               dpid, port, utilization * 100)
                    self.congested_links.add(port_key)
            else:
                if port_key in self.congested_links:
                    log.info("✅ Congestion cleared on %s port %d", dpid, port)
                    self.congested_links.remove(port_key)

def launch():
    core.registerNew(SimpleLoadBalancer)
