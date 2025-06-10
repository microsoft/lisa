from datetime import datetime
from enum import Enum
from typing import Dict, List, Type

from lisa import LisaException, messages, notifier, schema
from lisa.messages import (
    DescriptorPollThroughput,
    DiskPerformanceMessage,
    IPCLatency,
    NetworkLatencyPerformanceMessage,
    NetworkPPSPerformanceMessage,
    NetworkTCPPerformanceMessage,
    NetworkUDPPerformanceMessage,
    PerfMessage,
)
from lisa.util import fields_to_dict, plugin_manager

from .common_database import DatabaseMixin, DatabaseSchema


class MessageMap:
    def __init__(
        self,
        table_name: str,
        fields_map: Dict[str, str],
    ) -> None:
        self.table_name = table_name
        self.fields_map = fields_map


_default_fields_map: Dict[str, str] = {
    "TestCaseName": "test_case_name",
    "Platform": "platform",
    "Location": "location",
    "HostVersion": "host_version",
    "GuestOS": "guest_os_type",
    "GuestDistro": "distro_version",
    "VMSize": "vmsize",
    "KernelVersion": "kernel_version",
    "LISVersion": "lis_version",
    "Tool": "tool",
    "TestResultId": "test_result_id",
}

_network_fields_map: Dict[str, str] = {
    "IPVersion": "ip_version",
    "ProtocolType": "protocol_type",
    "DataPath": "data_path",
}


_message_table_map: Dict[type, MessageMap] = {
    DiskPerformanceMessage: MessageMap(
        table_name="Perf_Storage",
        fields_map={
            **_default_fields_map,
            "DiskSetup": "disk_setup_type",
            "BlockSize_KB": "block_size",
            "QDepth": "qdepth",
            "CoreCount": "core_count",
            "numjob": "numjob",
            "IODepth": "iodepth",
            "DiskCount": "disk_count",
            "seq_read_iops": "read_iops",
            "seq_read_lat_usec": "read_lat_usec",
            "rand_read_iops": "randread_iops",
            "rand_read_lat_usec": "randread_lat_usec",
            "seq_write_iops": "write_iops",
            "seq_write_lat_usec": "write_lat_usec",
            "rand_write_iops": "randwrite_iops",
            "rand_write_lat_usec": "randwrite_lat_usec",
            "TestType": "disk_type",
        },
    ),
    NetworkLatencyPerformanceMessage: MessageMap(
        table_name="Perf_Network_Latency",
        fields_map={
            **_default_fields_map,
            **_network_fields_map,
            "MaxLatency_us": "max_latency_us",
            "AverageLatency_us": "average_latency_us",
            "MinLatency_us": "min_latency_us",
            "Latency95Percentile_us": "latency95_percentile_us",
            "Latency99Percentile_us": "latency99_percentile_us",
            "Interval_us": "interval_us",
            "Frequency": "frequency",
        },
    ),
    NetworkPPSPerformanceMessage: MessageMap(
        table_name="Perf_Network_TCP_PPS",
        fields_map={
            **_default_fields_map,
            **_network_fields_map,
            "TestType": "test_type",
            "RxPpsMinimum": "rx_pps_minimum",
            "RxPpsAverage": "rx_pps_average",
            "RxPpsMaximum": "rx_pps_maximum",
            "TxPpsMinimum": "tx_pps_minimum",
            "TxPpsAverage": "tx_pps_average",
            "TxPpsMaximum": "tx_pps_maximum",
            "RxTxPpsMinimum": "rx_tx_pps_minimum",
            "RxTxPpsAverage": "rx_tx_pps_average",
            "RxTxPpsMaximum": "rx_tx_pps_maximum",
        },
    ),
    NetworkTCPPerformanceMessage: MessageMap(
        table_name="Perf_Network_TCP",
        fields_map={
            **_default_fields_map,
            **_network_fields_map,
            "NumberOfConnections": "connections_num",
            "Throughput_Gbps": "throughput_in_gbps",
            "Latency_ms": "latency_us",
            "TXpackets": "tx_packets",
            "RXpackets": "rx_packets",
            "PktsInterrupts": "pkts_interrupts",
            "NumberOfReceivers": "number_of_receivers",
            "NumberOfSenders": "number_of_senders",
            "SenderCyclesPerByte": "sender_cycles_per_byte",
            "ConnectionsCreatedTime": "connections_created_time",
            "RetransSegments": "retrans_segments",
            "ReceiverCyclesPerByte": "receiver_cycles_rer_byte",
            "PacketSize_KBytes": "buffer_size_bytes",
            "RxThroughput_Gbps": "rx_throughput_in_gbps",
            "TxThroughput_Gbps": "tx_throughput_in_gbps",
            "RetransmittedSegments": "retransmitted_segments",
            "CongestionWindowSize_KB": "congestion_windowsize_kb",
        },
    ),
    NetworkUDPPerformanceMessage: MessageMap(
        table_name="Perf_Network_UDP",
        fields_map={
            **_default_fields_map,
            **_network_fields_map,
            "SendBufSize_KBytes": "send_buffer_size",
            "NumberOfConnections": "connections_num",
            "TxThroughput_Gbps": "tx_throughput_in_gbps",
            "RxThroughput_Gbps": "rx_throughput_in_gbps",
            "DatagramLoss": "data_loss",
            "PacketSize_KBytes": "packet_size_kbytes",
            "NumberOfReceivers": "number_of_receivers",
            "NumberOfSenders": "number_of_senders",
        },
    ),
    IPCLatency: MessageMap(
        table_name="Perf_IPC_Latency",
        fields_map={
            **_default_fields_map,
            "AverageTimeInSec": "average_time_sec",
            "MinimumTimeInSec": "min_time_sec",
            "MaximumTimeInSec": "max_time_sec",
        },
    ),
    DescriptorPollThroughput: MessageMap(
        table_name="Perf_Descriptor_Poll_Throughput",
        fields_map={
            **_default_fields_map,
            "AverageOPS": "average_ops",
            "MinimumOPS": "min_ops",
            "MaximumOPS": "max_ops",
        },
    ),
}


class PerfDatabaseNotifier(DatabaseMixin, notifier.Notifier):
    """
    Its a database notifier which parse and insert performance test results.
    """

    # load perf tables only
    _perf_tables = [x.table_name for x in _message_table_map.values()]

    def __init__(self, runbook: DatabaseSchema) -> None:
        DatabaseMixin.__init__(self, runbook, self._perf_tables)
        notifier.Notifier.__init__(self, runbook)

    @classmethod
    def type_name(cls) -> str:
        return "lsg_perf"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DatabaseSchema

    def _process_message(self, message: messages.PerfMessage) -> None:
        assert isinstance(message, PerfMessage), (
            f"incorrect message type: {type(message)}. "
            "The LsgPerf notifier accept perf messages only."
        )

        message_type = type(message)
        map = _message_table_map.get(message_type, None)

        assert map, (
            f"not found perf message type for {type(message)}, "
            "make sure it's mapped in dict."
        )

        # convert message into dict
        message_dict = fields_to_dict(message, fields=map.fields_map.values())
        data_dict: Dict[str, str] = {}

        # convert above dict into dict with real table column
        # use enum.name if the type is enum
        for key, value in map.fields_map.items():
            temp = message_dict[value]
            if isinstance(temp, Enum):
                temp = temp.name
            data_dict[key] = temp

        try:
            perf_table = getattr(self.base.classes, map.table_name)
        except Exception as identifier:
            raise LisaException(
                f"cannot find table {map.table_name} in database. "
                f"error: {identifier}"
            )

        perf_result = perf_table(**data_dict)

        # fill in test run id
        run_id = plugin_manager.hook.get_test_run_id()[0]
        perf_result.TestRunId = run_id

        # fill in test result id in db
        perf_result.TestResultId = plugin_manager.hook.get_test_result_db_id(
            result_id=message.test_result_id
        )[0]
        perf_result.CreatedTime = datetime.utcnow()
        session = self.create_session()
        session.add(perf_result)
        self.commit_and_close_session(session)

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, PerfMessage):
            self._process_message(message)
        else:
            raise LisaException(f"unsupported message type: {type(message)}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [PerfMessage]
