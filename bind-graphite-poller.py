#!/usr/bin/env python

"""Insert BIND server/zone/memory statistics info into Graphite.

Handles the case where XML is found in a file as opposed to querying
BIND's statistics port synchronously.
"""

import argparse
import logging
import pickle
import socket
import struct
import sys
import time
import urllib2
import xml.etree.ElementTree as ET

LOGGING_FORMAT = "%(asctime)s : %(levelname)s : %(message)s"


class PollerError(Exception):
    """Base class when retrieving/parsing BIND XML. """
    pass


class Bind(object):
    """Bind class for BIND statistics XML."""

    def __init__(self, args):
        self._args = args
        self.bind_xml = ""
        self.carbon = self._args.carbon
        if self.carbon:
            self.carbon_host, self.carbon_port = self.carbon.split(":")

        if self._args.bind:
            self.hostname, self.port = self._args.bind.split(":")

            if self.hostname == "localhost":
                self.hostname = socket.gethostname().split(".")[0]
            else:
                self.hostname = self.hostname.split(".")[0]
        else:
            self.hostname = "FILE"

        self.is_xml_file = self._args.xml_path
        self.timestamp = time.time()
        self.xml_path = self._args.xml_path

    def SendMemoryStats(self):
        """Parse server memory statistics and send to carbon."""
        stats = []
        memory_tree = self.bind_xml.iterfind(".//bind/statistics/memory/summary/")
        for element in memory_tree:
            value = int(element.text)
            metric = "dns.%s.memory.%s" % (self.hostname, element.tag)
            stats.append((metric, (self.timestamp, value)))

        logging.debug("Memory Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)

    def SendServerStats(self):
        """Parse server non-zone related statistics and send to Carbon."""
        stats = []
        queries_in = self.bind_xml.iterfind(".//server/queries-in/rdtype")
        for rdtype in queries_in:
            metric = "dns.%s.queries-in.%s" % (self.hostname, rdtype.find("name").text)
            value = int(rdtype.find("counter").text)
            stats.append((metric, (self.timestamp, value)))

        requests = self.bind_xml.iterfind(".//server/requests/opcode")
        for request in requests:
            metric = "dns.%s.requests.%s" % (self.hostname, request.find("name").text)
            value = int(request.find("counter").text)
            stats.append((metric, (self.timestamp, value)))

        logging.debug("Server Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)


    def SendZoneStats(self):
        """Parse by view/zone statistics and send to Carbon."""
        stats = []
        zones_tree = self.bind_xml.iterfind(".//views/view/zones/zone")
        for zone in zones_tree:
            zone_name = zone.find("name").text
            zone_split = zone_name.split("/") # "foo.com/IN/viewname"
            if zone_split[1] != "IN":
                continue
            zone_name = zone_split[0]
            if len(zone_split) == 3:
                zone_view = zone_split[2]
            else:
                zone_view = False

            zone_compiled = zone_name.replace(".", "-")
            metric_base = "dns.%s.%s" % (self.hostname, zone_compiled)

            metric_serial = metric_base + ".serial"
            zone_serial = int(zone.find("serial").text)
            stats.append((metric_serial, (self.timestamp, zone_serial)))
            if zone_view:
                metric_counter = metric_base + "." + zone_view
            else:
                metric_counter = metric_base
            for counter in zone.iterfind(".//counters/"):
                value = int(counter.text)
                metric = metric_counter + "." + counter.tag
                stats.append((metric, (self.timestamp, value)))

        logging.debug("Zone Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)

    def ReadXml(self):
        """Read Bind statistics XML into self.bind_xml.

        If XML file path is passed, attempt to read the file.
        If no XML file path is given and host:port provided, query BIND.
        """
        if self.is_xml_file:
            with open(self.xml_path, "r") as xml_fh:
                xml_data = xml_fh.read()
            self.bind_xml = ET.fromstring(xml_data)
        else:
            try:
                req = urllib2.urlopen("http://%s:%s" % (self.hostname, self.port))
            except urllib2.URLError, u_error:
                logging.error("Unable to query BIND (%s) for statistics. Reason: %s.",
                              self.hostname,
                              u_error)
                raise PollerError
            self.bind_xml = ET.fromstring(req.read())

    def SendToCarbon(self, stats):
        if self.carbon is None:
            logging.info("No Carbon host:port specified which to send statistics.")
            return

        logging.debug("Pickling statistics to %s", self.carbon)
        payload = pickle.dumps(stats)
        header = struct.pack("!L", len(payload))
        message = header + payload
        try:
            logging.debug("Opening connection to Carbon at %s", self.carbon)
            carbon_sock = socket.create_connection((self.carbon_host, self.carbon_port), 10)
            logging.debug("Sending statistics to Carbon.")
            carbon_sock.sendall(message)
            logging.debug("Done sending statistics to Carbon.")
            carbon_sock.close()
            logging.debug("Closing connection to Carbon.")
        except socket.error, s_error:
            logging.error("Error sending to Carbon %s. Reason : %s", self.carbon, s_error)


def main():
    parser = argparse.ArgumentParser(description="Parse BIND statistics and insert them into Graphite.")
    parser.add_argument("--bind",
                        help="BIND DNS hostname and statistics port. Example: dns1:8053")
    parser.add_argument("--carbon",
                        help="Carbon hostname and pickle port for receiving statistics.",
                        default=None)
    parser.add_argument("--interval",
                        type=int,
                        default=60,
                        help="Seconds between polling/sending executions. Default: %(default)s.")
    parser.add_argument("--onetime",
                        action="store_true",
                        help="Query configured BIND host once and quit.")
    parser.add_argument("-v", "--verbose",
                        choices=["error", "info", "debug"],
                        default="info",
                        help="Verbosity of output. Choices: %(choices)s")
    parser.add_argument("--xml_path",
                        default=None,
                        help="Path to XML file containing BIND statistics to process.")

    args = parser.parse_args()
    if args.verbose == "error":
        logging_level = logging.ERROR
    elif args.verbose == "debug":
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    logging.basicConfig(format=LOGGING_FORMAT, level=logging_level)

    bind_obj = Bind(args)
    bind_obj.ReadXml()

    while True:
        logging.info("Gathering statistics to send to Carbon %s.",
                     args.carbon)
        bind_obj.SendServerStats()
        bind_obj.SendZoneStats()
        bind_obj.SendServerStats()
        bind_obj.SendMemoryStats()
        elapsed_time = time.time() - bind_obj.timestamp
        if bind_obj.carbon:
            logging.info("Finished sending BIND statistics to carbon. "
                         "(Elaped time: %.2f seconds.)", elapsed_time)

        if args.onetime:
            logging.info("One time query. Exiting.")
            return
        else:
            time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
