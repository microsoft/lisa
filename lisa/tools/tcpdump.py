# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from dataclasses import dataclass
from typing import List, Pattern

from lisa.executable import Tool
from lisa.util import find_groups_in_lines
from lisa.util.process import Process


@dataclass
class IpPacket:
    time: time.struct_time
    source: str
    destination: str
    extra: str = ""


class TcpDump(Tool):
    # 08:26:46.004382 IP 131.107.147.25.36387 > node-0.internal.cloudapp.net.ssh:
    #   Flags [.], ack 2212, win 1024, length 0
    # 08:26:46.737235 IP node-0.internal.cloudapp.net.33619 > 168.63.129.16.domain:
    #   47850+ [1au] PTR? 200.197.79.204.in-addr.arpa. (56)
    # 08:26:46.736965 IP a-0001.a-msedge.net > node-0.internal.cloudapp.net:
    #   ICMP echo reply, id 18491, seq 1, length 64
    _information_pattern: Pattern[str] = re.compile(
        r"^(?P<time>[\d:.]+) IP (?P<source>.*?)"
        r" > (?P<destination>.*?): (?P<extra>.*)$",
        re.MULTILINE,
    )

    @property
    def command(self) -> str:
        return "tcpdump"

    @property
    def can_install(self) -> bool:
        return False

    def dump_async(
        self,
        nic_name: str = "",
        filter: str = "",
        timeout: int = 5,
        packet_filename: str = "tcp_dump.pcap",
    ) -> Process:
        full_name = self.get_tool_path() / packet_filename
        # -n not resolve address to domain name.
        # -i specify the nic name
        # -w write to pcap file.
        command = (
            f"timeout {timeout} {self.command} -n -i {nic_name} {filter} -w {full_name}"
        )
        process = self.node.execute_async(cmd=command, shell=True, sudo=True)
        return process

    def parse(self, packet_filename: str = "tcp_dump.pcap") -> List[IpPacket]:
        full_name = self.get_tool_path() / packet_filename
        # -n not resolve address to domain name.
        # -r read from file
        output = self.run(
            f"-n -r {full_name}",
            expected_exit_code=0,
            expected_exit_code_failure_message=f"error on parse packet file: "
            f"{packet_filename}",
        ).stdout
        packets: List[IpPacket] = []
        results = find_groups_in_lines(output, self._information_pattern)
        for item in results:
            packet = IpPacket(
                time=time.strptime(item["time"], "%H:%M:%S.%f"),
                source=item["source"],
                destination=item["destination"],
                extra=item["extra"],
            )
            packets.append(packet)
        self._log.debug(f"{len(packets)} packets loaded.")

        return packets
