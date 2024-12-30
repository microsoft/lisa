# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
from typing import Any
import json
from xml.etree import ElementTree

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.process import Process


class PowerShell(Tool):
    @property
    def command(self) -> str:
        return "powershell"

    @property
    def can_install(self) -> bool:
        # TODO: install PowerShell core on Linux.
        return False

    def run_cmdlet_async(
        self,
        cmdlet: str,
        force_run: bool = False,
        sudo: bool = False,
    ) -> Process:
        # encoding command for any special characters
        self._log.debug(f"encoding command: {cmdlet}")
        encoded_command = base64.b64encode(cmdlet.encode("utf-16-le")).decode("utf-8")

        encoded_command = f"-EncodedCommand {encoded_command}"

        return self.run_async(
            encoded_command,
            force_run=force_run,
            sudo=sudo,
            shell=True,
            no_error_log=True,
            no_info_log=True,
            no_debug_log=True,
        )

    def run_cmdlet(
        self,
        cmdlet: str,
        output_json: bool = False,
        force_run: bool = False,
        sudo: bool = False,
        fail_on_error: bool = True,
        timeout: int = 600,
    ) -> Any:
        if output_json:
            cmdlet = f"{cmdlet} | ConvertTo-Json"
        process = self.run_cmdlet_async(
            cmdlet=cmdlet,
            force_run=force_run,
            sudo=sudo,
        )

        result = process.wait_result(timeout=timeout)
        if result.exit_code == 0:
            self._log.debug(f"stdout:\n{result.stdout}")
        else:
            stderr = self._parse_error_message(result.stderr)
            self._log.debug(f"stderr:\n{stderr}")
            if fail_on_error:
                raise LisaException(
                    f"non-zero exit code {result.exit_code} from cmdlet '{cmdlet}'. "
                    f"output:\n{result.stdout}"
                    f"error:\n{stderr}"
                )
        if output_json:
            return json.loads(result.stdout)
        return result.stdout

    def install_module(self, name: str) -> None:
        self.run_cmdlet(
            f"Install-Module -Name {name} -Scope CurrentUser "
            "-Repository PSGallery -Force"
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

        # remove security policy to run scripts
        self.run_cmdlet(
            "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope CurrentUser",
            fail_on_error=False,
        )

    def _parse_error_message(self, raw: str) -> str:
        # remove first line, which is "#< CLIXML"
        leading = "#< CLIXML"
        if raw.startswith(leading):
            raw = raw[len(leading) :]
        root = ElementTree.fromstring(raw)
        namespaces = {"ns": "http://schemas.microsoft.com/powershell/2004/04"}
        error_elements = root.findall(".//ns:S[@S='Error']", namespaces=namespaces)
        result = "".join([e.text for e in error_elements if e.text])

        result = result.replace("_x000D__x000A_", "\n")
        return result
