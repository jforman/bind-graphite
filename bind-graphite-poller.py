#!/usr/bin/env python

import argparse
import logging
import pickle
import socket
import struct
import time
import urllib2
import xml.etree.ElementTree as ET

LOGGING_FORMAT = "%(asctime)s : %(levelname)s : %(message)s"

class PollerError(Exception):
    pass

def get_bind_stats_xml(bindhostport):
    """Given a host:port, fetch XML from BIND statistics port."""
    try:
        req = urllib2.urlopen("http://%s" % bindhostport)
    except urllib2.URLError, u_error:
        logging.error("Unable to query BIND (%s) for statistics. Reason: %s.", bindhostport, u_error)
        raise PollerError

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

    logging.debug("Server Statistics for %s: %s", bind_host, stats)
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

    logging.debug("Zone Statistics for %s: %s", bind_host, stats)
    send_to_carbon(args.carbonhostport, stats)
    
def send_memory_stats(args, now, bind_host, bind_xml):
    stats = []
    memory_tree = bind_xml.iterfind(".//bind/statistics/memory/summary/")
    for element in memory_tree:
        value = int(element.text)
        metric = "dns.%s.memory.%s" % (bind_host, element.tag)
        stats.append((metric, (now, value)))

    logging.debug("Memory Statistics for %s: %s", bind_host, stats)
    send_to_carbon(args.carbonhostport, stats)

def send_to_carbon(carbonhostport, stats):
    if carbonhostport is None:
        logging.info("No Carbon host:port specified to send statistics to.")
        return

    logging.debug("Pickling statistics to %s", carbonhostport)
    (carbon_host, carbon_port) = carbonhostport.split(":")
    payload = pickle.dumps(stats)
    header = struct.pack("!L", len(payload))
    message = header + payload
    try:
        logging.debug("Opening connection to Carbon at %s", carbonhostport)
        carbon_sock = socket.create_connection((carbon_host, carbon_port), 10)
        logging.debug("Sending statistics to Carbon.")
        carbon_sock.sendall(message)
        logging.debug("Done sending statistics to Carbon.")
        carbon_sock.close()
        logging.debug("Closing connection to Carbon.")
    except socket.error, s_error:
        logging.error("Error sending to Carbon %s. Reason : %s", carbonhostport, s_error)

def main():
    parser = argparse.ArgumentParser(description="Parse BIND statistics and pass them off to Graphite.")
    parser.add_argument("--bindhostport",
                        help="BIND DNS hostname and statistics port. Example: dns1:8053")
    parser.add_argument("--carbonhostport",
                        help="Carbon hostname and pickle port for receiving statistics.",
                        default=None)
    parser.add_argument("--interval",
                        type=int,
                        default=60,
                        help="Time between polling BIND for statistics and sending to Graphite. Default: 60.")
    parser.add_argument("--onetime",
                        action="store_true",
                        help="Query configured BIND host once and quit.")
    parser.add_argument("-v", "--verbose",
                        choices=[1, 2, 3],
                        type=int,
                        default=2,
                        help="Verbosity of output. 1:ERROR, 2:INFO (Default), 3:DEBUG.")

    args = parser.parse_args()
    if args.verbose == 1:
        logging_level = logging.ERROR
    elif args.verbose == 3:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    logging.basicConfig(format=LOGGING_FORMAT, level=logging_level)
    (bind_host, bind_port) = args.bindhostport.split(":")
    hostname = bind_host.split(".")[0]

    while True:
        start_timestamp = time.time()
        logging.info("Gathering statistics to send to Carbon %s.", args.carbonhostport)
        try:
            bind_xml = ET.fromstring(get_bind_stats_xml(args.bindhostport))
        except PollerError:
            logging.error("Error encountered, skipping this iteration.")
            pass
        else:
            send_server_stats(args, int(start_timestamp), hostname, bind_xml)
            send_zones_stats(args, int(start_timestamp), hostname, bind_xml)
            send_memory_stats(args, int(start_timestamp), hostname, bind_xml)
            elapsed_time = time.time() - start_timestamp
            logging.info("Finished sending BIND statistics to carbon. (Elaped time: %.2f seconds.)", elapsed_time)

        if args.onetime:
            logging.info("One time query. Exiting.")
            break
        else:
            time.sleep(args.interval)
    

if __name__ == "__main__":
    main()
