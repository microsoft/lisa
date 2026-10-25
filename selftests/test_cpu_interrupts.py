# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.core.cpu import CPU
from lisa.node import Node
from lisa.operating_system import CpuArchitecture, Ubuntu
from lisa.tools import Ethtool, InterruptInspector, Lscpu
from lisa.tools.interrupt_inspector import Interrupt
from lisa.util import SkippedException


class VmbusInterruptTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, CPU).__wrapped__
        self.suite = object.__new__(suite_class)
        self.node = MagicMock(spec=Node)
        self.node.os = MagicMock(spec=Ubuntu)
        self.node.os.get_kernel_information.return_value.hardware_platform = (
            CpuArchitecture.X64
        )
        self.node.nics = MagicMock()
        self.node.nics.default_nic = "eth0"
        self.node.tools = MagicMock()
        self.log = MagicMock()
        self.ethtool = MagicMock(spec=Ethtool)
        self.ethtool.get_device_driver.return_value = " hv_netvsc"
        lscpu = MagicMock(spec=Lscpu)
        lscpu.get_thread_count.return_value = 4
        self.inspector = MagicMock(spec=InterruptInspector)
        self.inspector.get_interrupt_data.return_value = [
            Interrupt("HRE", [0, 0, 0, 0], 0, "Hyper-V reenlightenment interrupts"),
            Interrupt("HYP", [1, 1, 0, 0], 2, "Hypervisor callback interrupts"),
            Interrupt("HVS", [1, 1, 1, 1], 4, "Hyper-V stimer interrupts"),
        ]
        self.node.tools.__getitem__.side_effect = {
            Ethtool: self.ethtool,
            Lscpu: lscpu,
            InterruptInspector: self.inspector,
        }.__getitem__
        stress_patch = patch.object(self.suite, "_create_stimer_interrupts")
        self.stress = stress_patch.start()
        self.addCleanup(stress_patch.stop)

    def test_virtio_profile_is_not_a_netvsc_channel_distribution_test(self) -> None:
        self.ethtool.get_device_driver.return_value = " virtio_net"

        with self.assertRaisesRegex(SkippedException, "NetVSC"):
            self.suite.verify_vmbus_interrupts(node=self.node, log=self.log)

        self.stress.assert_not_called()

    def test_missing_netvsc_callback_activity_still_fails(self) -> None:
        with self.assertRaisesRegex(AssertionError, "Hypervisor callback"):
            self.suite.verify_vmbus_interrupts(node=self.node, log=self.log)

    def test_netvsc_profile_keeps_all_interrupt_assertions(self) -> None:
        self.inspector.get_interrupt_data.return_value[1] = Interrupt(
            "HYP", [1, 1, 1, 1], 4, "Hypervisor callback interrupts"
        )

        self.suite.verify_vmbus_interrupts(node=self.node, log=self.log)

        self.stress.assert_called_once_with(self.node, 4)
