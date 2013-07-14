# bind-graphite

I wanted a way to display the statistics provided via ISC BIND's XML statistics interface in a Graphite dashboard. This plugin parses that XML providing both process and zone-specific information to Graphite for visualization.

## Requirements

* ISC BIND. At least version 9.5.x, which provides the statistics-port configuration parameter.
* Python. At least version 2.7.x
* Carbon and Graphite

## Installation

Currently the Git repository is the canonoical way to grab this set of code. It is expected to run under /usr/local/bind-graphite/ if on OpenBSD, or /opt/bind-graphite on Ubuntu (or other Linux distributions).

An Upstart and rc.d controlling configuration files are provided to facilitate startup and shutdown of the poller. The Upstart configuration file contains the entire command-line necessary, therefore you will need to modify this file to contain the BIND host:port and Carbon host:port here. The OpenBSD rc.d file contains an example of options to append to /etc/rc.conf.local.

## Example

The poller has a default 60 second internal between checking BIND for statistics. A typical command line on OpenBSD will look like:

    /usr/local/bind-graphite/bind-graphite-poller.py --bind dns1:8053 --carbon monitor:2004
    
Zone and memory statistic metrics follow the nomenclature like the following:

    dns.dns1.memory.TotalUse
    dns.dns1.memory.InUse
    dns.dns1.vpn-mydomain-net.Requestv4
    
If views are configured, the metric name for each counter will reflect that fact.

    dns.dns1.vpn-mydomain-net.external.Requestv4

Period seperators in zone information are converted to hypens for use in Graphite. Such that vpn.mydomain.net would be displayed as vpn-mydomain-net for the metric structure.

## TODO

Create OpenBSD and Ubuntu packages to make distribution a bit easier.
