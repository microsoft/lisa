# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.case import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema
from lisa.node import Node
from lisa.sut_orchestrator.baremetal.platform_ import (
    BAREMETAL_PLATFORM_HEALTH_FILE,
    BareMetalPlatform,
    BareMetalPlatformUnavailableException,
)
from lisa.sut_orchestrator.baremetal.readychecker import ReadyChecker
from lisa.util import LisaException, SkippedException, constants
from lisa.util.logger import Logger


class BareMetalPlatformTestCase(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.log_path = Path(self.temporary_directory.name)
        self.run_log_path_patch = patch.object(
            constants, "RUN_LOCAL_LOG_PATH", self.log_path
        )
        self.run_log_path_patch.start()
        self.addCleanup(self.run_log_path_patch.stop)

        self.platform = BareMetalPlatform(schema.Platform())
        self.platform._cluster_runbook = MagicMock()
        self.platform._cluster_runbook.ready_checker = MagicMock()
        self.platform._cluster_runbook.ip_getter = None
        self.platform.ready_checker_factory = MagicMock()
        self.cluster = MagicMock()
        self.platform.cluster = self.cluster
        self.ready_checker = MagicMock(spec=ReadyChecker)
        self.platform.ready_checker_factory.create_by_runbook.return_value = (
            self.ready_checker
        )
        self.environment = MagicMock()
        self.node = MagicMock(spec=Node)
        self.node.index = 0
        self.environment.nodes.list.return_value = [self.node]
        self.log = MagicMock(spec=Logger)

    def test_deploy_environment_success_does_not_quarantine(self) -> None:
        self.ready_checker.is_ready.return_value = True
        node_context = SimpleNamespace(
            client=SimpleNamespace(connection=SimpleNamespace(address=""))
        )

        with (
            patch.object(self.platform, "_predeploy_environment") as predeploy,
            patch(
                "lisa.sut_orchestrator.baremetal.platform_.get_node_context",
                return_value=node_context,
            ),
        ):
            self.platform._deploy_environment(self.environment, self.log)

        predeploy.assert_called_once_with(self.environment, self.log)
        self.ready_checker.prepare.assert_called_once_with(self.node)
        self.cluster.deploy.assert_called_once_with(self.environment)
        self.cluster.recover_deployment.assert_not_called()
        self.assertIsNone(self.platform._unavailable_reason)
        self.assertFalse((self.log_path / BAREMETAL_PLATFORM_HEALTH_FILE).exists())

    def test_predeployment_readiness_failure_quarantines_platform(self) -> None:
        preparation_error = LisaException(
            "Cannot establish the pre-install root filesystem identity"
        )
        self.ready_checker.prepare.side_effect = preparation_error

        with (
            patch.object(self.platform, "_predeploy_environment") as predeploy,
            self.assertRaises(BareMetalPlatformUnavailableException) as failure,
        ):
            self.platform._deploy_environment(self.environment, self.log)

        self.assertIs(preparation_error, failure.exception.__cause__)
        self.assertIn(str(preparation_error), str(failure.exception))
        health = json.loads(
            (self.log_path / BAREMETAL_PLATFORM_HEALTH_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "reason": "pre_deployment_readiness_failed",
                "schema_version": 1,
                "status": "unavailable",
            },
            health,
        )
        predeploy.assert_called_once_with(self.environment, self.log)
        self.ready_checker.prepare.assert_called_once_with(self.node)
        self.cluster.deploy.assert_not_called()
        self.cluster.recover_deployment.assert_not_called()

        later_environment = MagicMock()
        with self.assertRaises(SkippedException) as skipped:
            self.platform._deploy_environment(later_environment, self.log)

        self.assertEqual(self.platform._unavailable_reason, str(skipped.exception))
        self.assertNotIn(str(preparation_error), str(skipped.exception))
        self.ready_checker.prepare.assert_called_once_with(self.node)
        self.cluster.deploy.assert_not_called()
        self.cluster.recover_deployment.assert_not_called()

    def test_recovery_failure_quarantines_and_skips_later_deployments(self) -> None:
        self.ready_checker.is_ready.side_effect = LisaException(
            "pre-install root filesystem is still active"
        )
        recovery_error = LisaException("iDRAC API request failed with status 500")
        self.cluster.recover_deployment.side_effect = recovery_error

        with (
            patch.object(self.platform, "_predeploy_environment") as predeploy,
            self.assertRaises(BareMetalPlatformUnavailableException) as failure,
        ):
            self.platform._deploy_environment(self.environment, self.log)

        self.assertIs(recovery_error, failure.exception.__cause__)
        self.assertIn(str(recovery_error), str(failure.exception))
        self.assertIsNotNone(self.platform._unavailable_reason)
        health = json.loads(
            (self.log_path / BAREMETAL_PLATFORM_HEALTH_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "reason": "deployment_recovery_failed",
                "schema_version": 1,
                "status": "unavailable",
            },
            health,
        )
        predeploy.assert_called_once_with(self.environment, self.log)
        self.ready_checker.prepare.assert_called_once_with(self.node)
        self.cluster.deploy.assert_called_once_with(self.environment)
        self.cluster.recover_deployment.assert_called_once_with(self.environment)

        later_environment = MagicMock()
        with self.assertRaises(SkippedException) as skipped:
            self.platform._deploy_environment(later_environment, self.log)

        self.assertEqual(self.platform._unavailable_reason, str(skipped.exception))
        self.assertNotIn(str(recovery_error), str(skipped.exception))
        predeploy.assert_called_once_with(self.environment, self.log)
        self.ready_checker.prepare.assert_called_once_with(self.node)
        self.cluster.deploy.assert_called_once_with(self.environment)
        self.cluster.recover_deployment.assert_called_once_with(self.environment)

    def test_failed_post_recovery_verification_quarantines_platform(self) -> None:
        readiness_errors = [
            LisaException("pre-install root filesystem is still active"),
            LisaException("recovery did not produce a verifiable fresh installation"),
        ]
        self.ready_checker.is_ready.side_effect = readiness_errors

        with (
            patch.object(self.platform, "_predeploy_environment"),
            self.assertRaises(BareMetalPlatformUnavailableException) as failure,
        ):
            self.platform._deploy_environment(self.environment, self.log)

        self.assertIs(readiness_errors[1], failure.exception.__cause__)
        self.cluster.recover_deployment.assert_called_once_with(self.environment)
        self.assertIsNotNone(self.platform._unavailable_reason)
