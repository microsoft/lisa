# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import Dict, Tuple, Type
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.executable import Tool
from lisa.node import Node
from lisa.operating_system import Cat, CBLMariner, FreeBSD, OperatingSystem, Ubuntu
from lisa.tools.chrony import Chrony
from lisa.tools.echo import Echo
from lisa.tools.ls import Ls
from lisa.util.logger import get_logger


class ChronyTestCase(TestCase):
    _configurations = (
        (Ubuntu, "/etc/chrony/chrony.conf"),
        (CBLMariner, "/etc/chrony.conf"),
        (FreeBSD, "/usr/local/etc/chrony.conf"),
    )

    def _create_chrony(
        self, os_type: Type[OperatingSystem]
    ) -> Tuple[Chrony, Dict[Type[Tool], MagicMock]]:
        node = MagicMock(spec=Node)
        node.log = get_logger("chrony-test")
        node.os = MagicMock(spec=os_type)
        node.tools = MagicMock()
        tools = {
            Cat: MagicMock(spec=Cat),
            Echo: MagicMock(spec=Echo),
            Ls: MagicMock(spec=Ls),
        }
        node.tools.__getitem__.side_effect = tools.__getitem__
        return Chrony(node), tools

    def test_makestep_updates_active_config_and_preserves_sources(self) -> None:
        for os_type, path in self._configurations:
            with self.subTest(os=os_type.__name__):
                chrony, tools = self._create_chrony(os_type)
                tools[Ls].path_exists.return_value = True
                tools[
                    Cat
                ].read.return_value = "pool example.invalid iburst\nmakestep 1.0 3\n"

                chrony.set_makestep("1.0 -1")

                content, destination = tools[Echo].write_to_file.call_args.args
                self.assertEqual(destination.as_posix(), path)
                self.assertIn("pool example.invalid iburst", content)
                self.assertIn("# makestep 1.0 3", content)
                self.assertIn("\nmakestep 1.0 -1\n", content)
                read_path = tools[Cat].read.call_args.args[0]
                self.assertEqual(PurePath(read_path).as_posix(), path)

    def test_missing_servers_are_added_to_active_config(self) -> None:
        for os_type, path in self._configurations:
            with self.subTest(os=os_type.__name__):
                chrony, tools = self._create_chrony(os_type)
                result = MagicMock(stdout="Number of sources = 0")

                with patch.object(chrony, "run", return_value=result):
                    chrony.set_server_setting()

                tools[Echo].run.assert_called()
                for call in tools[Echo].run.call_args_list:
                    self.assertTrue(call.args[0].endswith(f">> {path}"))
