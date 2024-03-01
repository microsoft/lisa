from assertpy import fail

from lisa import Node
from lisa.tools import Lscpu, Lspci
from lisa.util.constants import DEVICE_TYPE_SRIOV


class DpdkVfHelper:
    MLX_CX3 = "mlx_cx3"
    MLX_CX4 = "mlx_cx4"
    MLX_CX5 = "mlx_cx5"
    MSFT_MANA = "mana"
    SINGLE_QUEUE = "single"
    MULTI_QUEUE = "multi"
    SEND = "send"
    RECV = "receive"
    FWD = "forwarder"
    NOT_SET = "not_set"

    # single queue is implemented but unused to avoid test bloat
    _l3fwd_thresholds = {
        MLX_CX3: {
            MULTI_QUEUE: {SEND: 10},
        },
        MLX_CX4: {
            MULTI_QUEUE: {FWD: 15},
        },
        MLX_CX5: {
            MULTI_QUEUE: {FWD: 20},
        },
        MSFT_MANA: {
            MULTI_QUEUE: {FWD: 160},
        },
    }

    _testpmd_thresholds = {
        MLX_CX3: {
            SINGLE_QUEUE: {SEND: 6_000_000, RECV: 4_000_000},
            MULTI_QUEUE: {SEND: 20_000_000, RECV: 10_000_000},
        },
        MLX_CX4: {
            SINGLE_QUEUE: {SEND: 7_000_000, RECV: 4_000_000},
            MULTI_QUEUE: {SEND: 25_000_000, RECV: 12_000_000},
        },
        MLX_CX5: {
            SINGLE_QUEUE: {SEND: 8_000_000, RECV: 4_000_000},
            MULTI_QUEUE: {SEND: 28_000_000, RECV: 14_000_000},
        },
        MSFT_MANA: {
            SINGLE_QUEUE: {SEND: 18_000_000, RECV: 8_000_000},
            MULTI_QUEUE: {SEND: 49_000_000, RECV: 48_000_000},
        },
    }

    def _set_network_hardware(self) -> None:
        lspci = self._node.tools[Lspci]
        device_list = lspci.get_devices_by_type(DEVICE_TYPE_SRIOV)
        is_connect_x3 = any(["ConnectX-3" in dev.device_info for dev in device_list])
        is_connect_x4 = any(["ConnectX-4" in dev.device_info for dev in device_list])
        is_connect_x5 = any(["ConnectX-5" in dev.device_info for dev in device_list])
        is_mana = any(["Microsoft" in dev.vendor for dev in device_list])
        if is_mana:
            self._hardware = self.MSFT_MANA
        elif is_connect_x3:
            self._hardware = self.MLX_CX3
        elif is_connect_x4:
            self._hardware = self.MLX_CX4
        elif is_connect_x5:
            self._hardware = self.MLX_CX5
        else:
            fail(
                "Test bug: unexpected network hardware! "
                "SRIOV is likely not enabled or this is a new, "
                "unimplemented bit of network hardware"
            )
        self._node.log.debug(f"Created threshold helper for nic: {self._hardware}")

    def __init__(self, should_enforce: bool, node: Node) -> None:
        self._node = node
        is_large_core_vm = self._node.tools[Lscpu].get_core_count() >= 64
        self.use_strict_checks = should_enforce and is_large_core_vm
        self._set_network_hardware()
        self._direction = self.NOT_SET
        self._queue_type = self.SINGLE_QUEUE

    def get_hw_name(self) -> str:
        return self._hardware

    def set_sender(self) -> None:
        self._direction = self.SEND

    def set_receiver(self) -> None:
        self._direction = self.RECV

    def set_forwader(self) -> None:
        self._direction = self.FWD

    def set_multiple_queue(self) -> None:
        self._queue_type = self.MULTI_QUEUE

    def set_single_queue(self) -> None:
        self._queue_type = self.SINGLE_QUEUE

    def is_mana(self) -> bool:
        return self._hardware == self.MSFT_MANA

    def is_connect_x3(self) -> bool:
        return self._hardware == self.MLX_CX3

    def is_connect_x4(self) -> bool:
        return self._hardware == self.MLX_CX4

    def is_connect_x5(self) -> bool:
        return self._hardware == self.MLX_CX5

    def get_threshold_testpmd(self) -> int:
        # default nonstrict threshold for pps
        # set up top to appease the type checker
        threshold = 3_000_000
        if self._direction == self.NOT_SET:
            fail(
                "Test bug: testpmd sender/receiver status was "
                "not set before threshold fetch. "
                "Make sure to call vf_helper.set_sender() or"
                "vf_helper.set_receiver() before starting tests."
            )
        if not self.use_strict_checks:
            self._node.log.debug(
                f"Generated non-strict threshold for {self._hardware}: {threshold}"
            )
            return threshold

        try:
            dpdk_hw = self._testpmd_thresholds[self._hardware]
            qtype = dpdk_hw[self._queue_type]
            threshold = qtype[self._direction]
        except KeyError:
            fail(
                "Test bug, invalid hardware or direction "
                "key passed to DpdkHardware.get_threshold!"
            )
        self._node.log.debug(
            f"Generated strict threshold for {self._hardware}: {threshold}"
        )
        return threshold

    def get_threshold_l3fwd(self) -> int:
        # default nonstrict threshold for pps
        # set up top to appease the type checker
        threshold_gbps = 3
        if self._direction != self.FWD:
            fail(
                "Test bug: testpmd sender/receiver status was "
                "not set to FWD before threshold fetch. "
                "Make sure to call vf_helper.set_forwarder() or"
                "vf_helper.set_receiver() before starting tests."
            )
        if not self.use_strict_checks:
            self._node.log.debug(
                f"Generated non-strict threshold for {self._hardware}: {threshold_gbps}"
            )
            return threshold_gbps

        try:
            dpdk_hw = self._l3fwd_thresholds[self._hardware]
            qtype = dpdk_hw[self._queue_type]
            threshold_gbps = qtype[self._direction]
        except KeyError:
            fail(
                "Test bug, invalid hardware or direction "
                "key passed to DpdkHardware.get_threshold! "
                f"hw: {self._hardware} direction: {self._direction} qtype: {self._queue_type}"
            )
        self._node.log.debug(
            f"Generated strict threshold for {self._hardware}: {threshold_gbps}"
        )
        return threshold_gbps
