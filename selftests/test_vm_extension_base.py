# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest.case import TestCase
from unittest.mock import MagicMock

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import LisaException
from lisa.util import SkippedException


class VmExtensionTestBaseTestCase(TestCase):
    def test_boot_validation_does_not_dirty_node_for_invalid_version(self) -> None:
        suite = object.__new__(VmExtensionTestBase)
        node = MagicMock()
        extension = MagicMock()
        node.features.__getitem__.return_value = extension
        extension.normalize_type_handler_version.side_effect = LisaException("invalid")
        variables = {
            "extension_publisher": "publisher",
            "extension_type": "type",
            "extension_version": "invalid",
        }

        with self.assertRaises(SkippedException):
            suite._boot_validation(
                node=node,
                log=MagicMock(),
                variables=variables,
                settings={},
                mark_dirty_before_install=True,
            )

        node.mark_dirty.assert_not_called()

    def test_boot_validation_dirties_node_immediately_before_install(self) -> None:
        suite = object.__new__(VmExtensionTestBase)
        node = MagicMock()
        extension = MagicMock()
        node.features.__getitem__.return_value = extension
        extension.normalize_type_handler_version.return_value = ("1.0", False)
        extension.get_installed_type_handler_version.return_value = "1.0.0"
        suite._install = MagicMock(return_value={"provisioning_state": "Succeeded"})
        suite._assert_provisioned = MagicMock()
        suite._assert_vm_reachable = MagicMock()
        suite._uninstall = MagicMock()
        calls = MagicMock()
        calls.attach_mock(node.mark_dirty, "mark_dirty")
        calls.attach_mock(suite._install, "install")

        suite._boot_validation(
            node=node,
            log=MagicMock(),
            variables={
                "extension_publisher": "publisher",
                "extension_type": "type",
                "extension_version": "1.0",
            },
            settings={},
            mark_dirty_before_install=True,
        )

        self.assertEqual("mark_dirty", calls.method_calls[0][0])
        self.assertEqual("install", calls.method_calls[1][0])
        node.mark_dirty.assert_called_once_with()
        suite._install.assert_called_once()
