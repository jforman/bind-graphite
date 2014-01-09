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
from pybindxml import reader

LOGGING_FORMAT = "%(asctime)s : %(levelname)s : %(message)s"


class PollerError(Exception):
    """Base class when retrieving/parsing BIND XML. """
    pass


class Bind(object):
    """Bind class for BIND statistics XML."""

    def __init__(self, args, bindxml):
        self._args = args
        self.bindxml = bindxml
        self.carbon = self._args.carbon
        if self.carbon:
            self.carbon_host, self.carbon_port = self.carbon.split(":")

        self.hostname, self.port = self._args.bind.split(":")

        if self.hostname == "localhost":
            self.hostname = socket.gethostname().split(".")[0]
        else:
            self.hostname = self.hostname.split(".")[0]
        self.timestamp = time.time()

    def SendMemoryStats(self):
        """Parse server memory statistics and send to carbon."""
        stats = []
        for element, value in self.bindxml.stats.memory_stats.items():
            metric = "dns.%s.memory.%s" % (self.hostname, element)
            stats.append((metric, (self.timestamp, value)))

        logging.debug("Memory Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)

    def SendQueryStats(self):
        """Parse server query related statistics and send to Carbon."""
        stats = []
        for element, value in self.bindxml.stats.query_stats.items():
            metric = "dns.%s.query.%s" % (self.hostname, element)
            stats.append((metric, (self.timestamp, value)))

        logging.debug("Query Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)


    def SendZoneStats(self):
        """Parse by view/zone statistics and send to Carbon."""
        stats = []
        for domain, view in self.bindxml.stats.zone_stats.items():
            for view_name, counters in view.items():
                for counter, value_dict in counters.items():
                    if counter == "serial":
                        # serial is a special-case where it is just an integer,
                        # and not part of a dict. in this case, just create one.
                        value_dict = {'value': value_dict}
                    domain_compiled = domain.replace(".", "-")
                    metric = "dns.%s.%s.%s.%s" % (self.hostname,
                                                  domain_compiled,
                                                  view_name,
                                                  counter)
                    stats.append((metric, (self.timestamp, value_dict['value'])))

        logging.debug("Zone Statistics for %s: %s", self.hostname, stats)
        self.SendToCarbon(stats)

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
    parser.add_argument("--verbose",
                        choices=["error", "info", "debug"],
                        default="info",
                        help="Verbosity of output. Choices: %(choices)s")

    args = parser.parse_args()
    if args.verbose == "error":
        logging_level = logging.ERROR
    elif args.verbose == "debug":
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    logging.basicConfig(format=LOGGING_FORMAT, level=logging_level)

    bindxml_obj = reader.BindXmlReader(host=args.bind.split(":")[0],
                                       port=args.bind.split(":")[1])
    bindxml_obj.get_stats()
    poller_obj = Bind(args, bindxml_obj)

    while True:
        logging.info("Gathering statistics to send to Carbon %s.",
                     args.carbon)
        bindxml_obj.get_stats()
        poller_obj = Bind(args, bindxml_obj)

        poller_obj.SendZoneStats()
        poller_obj.SendQueryStats()
        poller_obj.SendMemoryStats()
        elapsed_time = time.time() - poller_obj.timestamp
        if poller_obj.carbon:
            logging.info("Finished sending BIND statistics to carbon. "
                         "(Elaped time: %.2f seconds.)", elapsed_time)

        if args.onetime:
            logging.info("One time query. Exiting.")
            break
        else:
            time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
