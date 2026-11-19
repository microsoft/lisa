# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PureWindowsPath
from unittest import TestCase
from unittest.mock import Mock, call, patch

import requests

from lisa import schema
from lisa.node import Node
from lisa.sut_orchestrator.baremetal import schema as baremetal_schema
from lisa.sut_orchestrator.baremetal.cluster.pxe import (
    Ip9285StartStop,
    RemoteComSerialConsole,
)
from lisa.sut_orchestrator.baremetal.context import get_node_context
from lisa.util import LisaException


class BaremetalPxeTestCase(TestCase):
    def setUp(self) -> None:
        self.node = Node.create(0, schema.LocalNode())

    def test_power_request_formats_and_restart_sequence(self) -> None:
        for use_p6_api in (False, True):
            for port in ("1", "2"):
                with self.subTest(use_p6_api=use_p6_api, port=port):
                    config = schema.load_by_type(
                        baremetal_schema.PxeCluster,
                        {
                            "type": "pxe",
                            "start_stop": {
                                "type": "Ip9285",
                                "Ip9285": {
                                    "host": "192.0.2.2",
                                    "username": "test-user",
                                    "password": "test-password",
                                    "port_id": port,
                                    "use_p6_api": use_p6_api,
                                },
                            },
                        },
                    )
                    get_node_context(self.node).cluster = config
                    power = Ip9285StartStop(
                        schema.FeatureSettings(type="StartStop"), self.node, Mock()
                    )
                    power.initialize()
                    control = f"&p6{port}" if use_p6_api else f"+{port}"
                    url = (
                        "http://192.0.2.2/set.cmd?"
                        "user=test-user+pass=test-password+cmd=setpower"
                        f"{control}"
                    )
                    with patch(
                        "lisa.sut_orchestrator.baremetal.cluster.pxe.requests.get"
                    ) as get, patch(
                        "lisa.sut_orchestrator.baremetal.cluster.pxe.sleep"
                    ) as sleep:
                        operations = Mock()
                        operations.attach_mock(get, "get")
                        operations.attach_mock(sleep, "sleep")
                        power.restart()
                        self.assertEqual(
                            operations.mock_calls,
                            [
                                call.get(f"{url}=0", timeout=3),
                                call.get().raise_for_status(),
                                call.sleep(3),
                                call.get(f"{url}=1", timeout=3),
                                call.get().raise_for_status(),
                            ],
                        )

    def test_power_http_failure_is_not_retried(self) -> None:
        power = Ip9285StartStop(
            schema.FeatureSettings(type="StartStop"), self.node, Mock()
        )
        power._request_cmd = "http://192.0.2.2/set.cmd?cmd=setpower&p61"
        with patch(
            "lisa.sut_orchestrator.baremetal.cluster.pxe.requests.get"
        ) as get, patch("lisa.sut_orchestrator.baremetal.cluster.pxe.sleep") as sleep:
            get.return_value.raise_for_status.side_effect = requests.HTTPError(
                "controller rejected request"
            )
            with self.assertRaises(requests.HTTPError):
                power._restart()
            get.assert_called_once()
            sleep.assert_not_called()

    def test_serial_handshake_sends_two_newlines(self) -> None:
        serial = self._serial()
        with patch.object(serial._serial_node, "execute_async") as execute:
            process = execute.return_value
            process.wait_output.side_effect = [False, True]
            serial._connect()
        process.input.assert_called_once_with("\n\n")
        self.assertIs(serial._process, process)
        execute.assert_called_once_with('plink -serial " COM10" -sercfg 115200,8,n,1,N')

    def test_serial_open_failure_stops_before_handshake(self) -> None:
        serial = self._serial()
        with patch.object(serial._serial_node, "execute_async") as execute:
            process = execute.return_value
            process.wait_output.return_value = True
            with self.assertRaisesRegex(
                LisaException, "failed to connect serial console"
            ):
                serial._connect()
        process.kill.assert_called_once()
        process.input.assert_not_called()

    def _serial(self) -> RemoteComSerialConsole:
        context = get_node_context(self.node)
        context.cluster = schema.load_by_type(
            baremetal_schema.PxeCluster,
            {
                "type": "pxe",
                "serial_console": {
                    "type": "remote_com",
                    "remote_com": {
                        "connection": {"address": "192.0.2.1", "username": "test-user"}
                    },
                },
            },
        )
        context.client = baremetal_schema.PxeClient(
            serial_console=baremetal_schema.SerialConsoleClient(port="COM10")
        )
        serial = RemoteComSerialConsole(
            schema.FeatureSettings(type="SerialConsole"), self.node, Mock()
        )
        serial._serial_node = Mock()
        serial._plink_path = PureWindowsPath("plink")
        return serial
