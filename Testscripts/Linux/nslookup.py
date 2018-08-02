#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
import argparse
import sys
import socket

parser = argparse.ArgumentParser()

parser.add_argument('-n', '--hostname', help='hostname or fqdn', required=True)
args = parser.parse_args()

print socket.gethostbyname(args.hostname)