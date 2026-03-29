# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
from typing import Any

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.tools import Chmod


class Mdatp(Tool):
    @property
    def command(self) -> str:
        return "mdatp"

    @property
    def can_install(self) -> bool:
        return True

    def get_mde_installer(self) -> bool:
        if not hasattr(self, "mde_installer"):
            wget = self.node.tools[Wget]

            download_path = wget.get(
                url="https://raw.githubusercontent.com/microsoft/mdatp-xplat/"
                "master/linux/installation/mde_installer.sh",
                filename="mde_installer.sh",
            )
            self.mde_installer = download_path
            self.node.tools[Chmod].update_folder(self.mde_installer, "777", sudo=True)
        return True

    def _install(self) -> bool:
        if not self.get_mde_installer():
            self._log.error(
                "Unable to download mde_installer.sh script. MDE can't be installed"
            )

        self._log.info("Installing MDE")
        result1 = self.node.execute(
            f"{self.mde_installer} --install", shell=True, sudo=True
        )
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
            self._log.error(
                "Unable to download mde_installer.sh script. MDE can't be onboarded"
            )

        self._log.info("Onboarding MDE")
        result1 = self.node.execute(
            f"{self.mde_installer} --onboard {download_path}", shell=True, sudo=True
        )
        self._log.info(result1)

        output = self.get_result("health --field licensed")

        self._log.info(output)

        return bool(output == ["true"])

    def get_result(
        self,
        arg: str,
        json_out: bool = False,
        sudo: bool = False,
    ) -> Any:
        if json_out:
            arg += " --output json"
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
