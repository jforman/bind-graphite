#!/usr/bin/env python

import argparse
import pickle
import socket
import struct
import time
import urllib2
import xml.etree.ElementTree as ET


def get_bind_stats_xml(bindhostport):
    """Given a host:port, fetch XML from BIND statistics port."""
    req = urllib2.urlopen("http://%s" % bindhostport)
    xml_data = req.read()
    return xml_data

def send_server_stats(args, now, bind_host, bind_xml):
    stats = []
    queries_in = bind_xml.iterfind(".//server/queries-in/rdtype")
    for rdtype in queries_in:
        metric = "dns.%s.queries-in.%s" % (bind_host, rdtype.find("name").text)
        value = int(rdtype.find("counter").text)
        stats.append((metric, (now, value)))

    requests = bind_xml.iterfind(".//server/requests/opcode")
    for request in requests:
        metric = "dns.%s.requests.%s" % (bind_host, request.find("name").text)
        value = int(request.find("counter").text)
        stats.append((metric, (now, value)))

    send_to_carbon(args.carbonhostport, stats)

def send_zones_stats(args, now, bind_host, bind_xml):
    stats = []
    zones_tree = bind_xml.iterfind(".//views/view/zones/zone")
    for zone in zones_tree:
        zone_name = zone.find("name").text
        if not zone_name.endswith("/IN"):
            continue
        zone_name = zone_name.rstrip("/IN")
        zone_compiled = zone_name.replace(".", "-")
        for counter in zone.iterfind(".//counters/"):
            value = int(counter.text)
            metric = "dns.%s.zone.%s.%s" % (bind_host, zone_compiled, counter.tag)
            stats.append((metric, (now, value)))

    send_to_carbon(args.carbonhostport, stats)
    
def send_memory_stats(args, now, bind_host, bind_xml):
    stats = []
    memory_tree = bind_xml.iterfind(".//bind/statistics/memory/summary/")
    for element in memory_tree:
        value = int(element.text)
        metric = "dns.%s.memory.%s" % (bind_host, element.tag)
        stats.append((metric, (now, value)))

    send_to_carbon(args.carbonhostport, stats)

def send_to_carbon(carbonhostport, stats):
    (carbon_host, carbon_port) = carbonhostport.split(":")
    payload = pickle.dumps(stats)
    header = struct.pack("!L", len(payload))
    message = header + payload
    carbon_sock = socket.create_connection((carbon_host, carbon_port), 10)
    carbon_sock.sendall(message)
    carbon_sock.close()


def main():
    parser = argparse.ArgumentParser(description="Parse BIND statistics and pass them off to Graphite.")
    parser.add_argument("--bindhostport",
                        help="BIND DNS hostname and statistics port. Example: dns1:8053")
    parser.add_argument("--carbonhostport",
                        help="Carbon hostname and pickle port for receiving statistics.")
    parser.add_argument("--interval",
                        type=int,
                        default=60,
                        help="Time between polling BIND for statistics and sending to Graphite. Default: 60.")

    args = parser.parse_args()
    (bind_host, bind_port) = args.bindhostport.split(":")
    stats = []

    while True:
        start_timestamp = time.time()
        print "Sending BIND statistics to carbon %s. Interval: %d seconds." % (args.carbonhostport, args.interval)
        bind_xml = ET.fromstring(get_bind_stats_xml(args.bindhostport))
        send_server_stats(args, int(start_timestamp), bind_host, bind_xml)
        send_zones_stats(args, int(start_timestamp), bind_host, bind_xml)
        send_memory_stats(args, int(start_timestamp), bind_host, bind_xml)
        elapsed_time = time.time() - start_timestamp
        print "Finished sending BIND statistics to carbon. (Elaped time: %.2f seconds.)" % elapsed_time
        time.sleep(args.interval)
    

if __name__ == "__main__":
    main()
