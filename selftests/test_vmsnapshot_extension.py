# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from contextlib import ExitStack
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from azure.core.exceptions import HttpResponseError

from lisa.microsoft.testsuites.vm_extensions.vmsnapshot_extension import (
    VmSnapsotLinuxBVTExtension,
)
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import LisaException

MODULE = "lisa.microsoft.testsuites.vm_extensions.vmsnapshot_extension"
VM_CHANGE = (
    "Changes were made to the Virtual Machine 'test-vm' while the operation "
    "'Create Restore Point' was in progress."
)


class VmSnapshotRetryTestCase(TestCase):
    def setUp(self) -> None:
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.client = MagicMock()
        collection = self.client.restore_point_collections.create_or_update.return_value
        collection.provisioning_state = "Succeeded"
        restore_point = self.client.restore_points.get.return_value
        restore_point.provisioning_state = "Succeeded"
        restore_point.consistency_mode = "FileSystemConsistent"
        patches.enter_context(
            patch(f"{MODULE}.get_compute_client", return_value=self.client)
        )
        context = MagicMock(resource_group_name="test-rg", vm_name="test-vm")
        patches.enter_context(patch(f"{MODULE}.get_node_context", return_value=context))
        self.wait = patches.enter_context(patch(f"{MODULE}.wait_operation"))
        self.sleep = patches.enter_context(
            patch(f"{MODULE}.time.sleep", side_effect=self._advance_time)
        )
        self.elapsed = 0.0
        self.log = MagicMock()
        self.node = MagicMock()
        self.node.capability.get_extended_runbook.return_value = AzureNodeSchema(
            location="westus3"
        )
        self.environment = MagicMock()
        self.environment.platform = MagicMock(spec=AzurePlatform)
        self.environment.platform.subscription_id = "test-subscription"
        self.suite = inspect.unwrap(VmSnapsotLinuxBVTExtension)(MagicMock())

    def _advance_time(self, seconds: float) -> None:
        self.elapsed += seconds

    def _run(self) -> None:
        self.suite.verify_vmsnapshot_extension(self.log, self.node, self.environment)

    def test_vm_updates_can_settle_before_retry_budget_expires(self) -> None:
        poller = MagicMock()

        def create_when_ready(**kwargs: Any) -> MagicMock:
            if self.elapsed < 140:
                raise HttpResponseError(message=VM_CHANGE)
            return poller

        self.client.restore_points.begin_create.side_effect = create_when_ready
        self._run()
        self.assertEqual(195, self.elapsed)
        self.assertEqual(7, self.client.restore_points.begin_create.call_count)
        self.assertEqual(
            [call(5), call(10), call(20), call(40), call(60), call(60)],
            self.sleep.call_args_list,
        )
        self.assertEqual(6, self.log.warning.call_count)
        self.client.restore_points.get.assert_called_once()

    def test_conflict_from_async_operation_is_retried(self) -> None:
        self.wait.side_effect = [HttpResponseError(message=VM_CHANGE), None]
        self._run()
        self.assertEqual(2, self.client.restore_points.begin_create.call_count)
        self.sleep.assert_called_once_with(5)
        self.client.restore_points.get.assert_called_once()
        self.assertIn(VM_CHANGE, self.log.warning.call_args.args[0])

    def test_exhaustion_preserves_last_azure_error(self) -> None:
        error = HttpResponseError(message=VM_CHANGE)
        self.client.restore_points.begin_create.side_effect = error
        with self.assertRaisesRegex(LisaException, "after 10 attempts") as raised:
            self._run()
        self.assertIs(error, raised.exception.__cause__)
        self.assertIn(VM_CHANGE, str(raised.exception))
        self.assertEqual(10, self.client.restore_points.begin_create.call_count)
        self.assertEqual(9, self.sleep.call_count)
        self.assertEqual(375, self.elapsed)
        self.client.restore_points.get.assert_not_called()

    def test_nonretryable_azure_error_is_preserved(self) -> None:
        error = HttpResponseError(message="AuthorizationFailed")
        self.client.restore_points.begin_create.side_effect = error
        with self.assertRaises(HttpResponseError) as raised:
            self._run()
        self.assertIs(error, raised.exception)
        self.client.restore_points.begin_create.assert_called_once()
        self.sleep.assert_not_called()

    def test_non_azure_error_is_not_retried_by_message(self) -> None:
        error = ValueError(VM_CHANGE)
        self.client.restore_points.begin_create.side_effect = error
        with self.assertRaises(ValueError) as raised:
            self._run()
        self.assertIs(error, raised.exception)
        self.client.restore_points.begin_create.assert_called_once()
        self.sleep.assert_not_called()

    def test_success_still_validates_consistency(self) -> None:
        for mode in ("FileSystemConsistent", "ApplicationConsistent"):
            with self.subTest(mode=mode):
                self.client.restore_points.get.return_value.consistency_mode = mode
                self._run()
        self.assertEqual(2, self.client.restore_points.get.call_count)
        self.sleep.assert_not_called()

    def test_invalid_consistency_is_not_retried(self) -> None:
        self.client.restore_points.get.return_value.consistency_mode = "CrashConsistent"
        with self.assertRaisesRegex(ValueError, "consistency mode"):
            self._run()
        self.client.restore_points.begin_create.assert_called_once()
        self.sleep.assert_not_called()
