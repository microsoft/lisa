# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import unittest
from unittest.mock import MagicMock
from lisa.environment import Environment
from lisa.sut_orchestrator.libvirt.ch_platform import CloudHypervisorPlatform
from lisa import schema

class TestCloudHypervisorPlatformEnvInfo(unittest.TestCase):
    def test_vmm_version_in_environment_information(self):
        # Create a fake runbook and platform
        runbook = schema.Platform(type="cloud_hypervisor", hosts=[schema.RemoteHost(address="1.2.3.4", username="user", private_key_file="/dev/null")])
        platform = CloudHypervisorPlatform(runbook)
        # Patch _get_vmm_version to return a known value
        platform._get_vmm_version = MagicMock(return_value="1.2.3-test")
        platform.vmm_version = "1.2.3-test"
        # Set up a fake environment and assign the platform
        env = MagicMock(spec=Environment)
        env.platform = platform
        # The platform's _get_environment_information should include vmm_version
        info = platform._get_environment_information(env)
        self.assertIn("vmm_version", info)
        self.assertEqual(info["vmm_version"], "1.2.3-test")

if __name__ == "__main__":
    unittest.main()
