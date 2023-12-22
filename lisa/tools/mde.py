# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import json
import requests
from pathlib import Path
from typing import Any

from lisa.executable import Tool
from lisa.executable import CustomScriptBuilder, CustomScript
from lisa.base_tools import Wget

class MDE(Tool):
    @property
    def command(self) -> str:
        return "mdatp"

    @property
    def can_install(self) -> bool:
        return True

    def get_mde_installer(self) -> bool:
        if not hasattr(self, '_mde_installer'):
            response = requests.get("https://raw.githubusercontent.com/microsoft/mdatp-xplat/master/linux/installation/mde_installer.sh")
            if response.ok:
                script = response.text
                import tempfile
                _, self.mde_installer_script = tempfile.mkstemp(prefix='mde_installer', suffix='.sh')
                with open(self.mde_installer_script, 'w') as writer:
                    writer.write(script)
                self._mde_installer = CustomScriptBuilder(Path(os.path.dirname(self.mde_installer_script)),
                                                [os.path.basename(self.mde_installer_script)])
                return True
            return False
        return True

    def _install(self) -> bool:
        if not self.get_mde_installer():
           self._log.error("Unable to download mde_installer.sh script. MDE can't be installed")

        mde_installer: CustomScript = self.node.tools[self._mde_installer]
        self._log.info('Installing MDE')
        result1 = mde_installer.run(parameters="--install", sudo=True)
        self._log.info(result1)

        return self._check_exists()


    def onboard(self, onboarding_script_sas_uri: str) -> bool:
        if not self._check_exists():
            self._log.error("MDE is not installed, onboarding not possible")
            return False

        wget = self.node.tools[Wget]

        download_path = wget.get(
            url=onboarding_script_sas_uri,
            filename="MicrosoftDefenderATPOnboardingLinuxServer.py",
        )

        if not self.get_mde_installer():
           self._log.error("Unable to download mde_installer.sh script. MDE can't be onboarded")

        script: CustomScript = self.node.tools[self._mde_installer]

        self._log.info('Onboarding MDE')
        result1 = script.run(parameters=f"--onboard {download_path}", sudo=True)
        self._log.info(result1)

        output = self.get_result('health --field licensed')

        self._log.info(output)

        return bool(output == ['true'])


    def get_result(
        self,
        arg: str,
        json_out: bool = False,
        sudo: bool = False,
    ) -> Any:
        if json_out:
            arg += ' --output json'
        result = self.run(
            arg,
            sudo=sudo,
            shell=True,
            force_run=True,
        )

        result.assert_exit_code(include_output=True)
        if json_out:
            return json.loads(result.stdout)
        return result.stdout.split()


