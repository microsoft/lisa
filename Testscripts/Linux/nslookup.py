#!/usr/bin/python

import argparse
import sys
import socket

parser = argparse.ArgumentParser()

parser.add_argument('-n', '--hostname', help='hostname or fqdn', required=True)
args = parser.parse_args()

print socket.gethostbyname(args.hostname)