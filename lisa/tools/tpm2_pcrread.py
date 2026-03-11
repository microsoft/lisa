# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Dict, List, Optional, Sequence, Union

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException, UnsupportedDistroException


class Tpm2Pcrread(Tool):
    """tpm2_pcrread reads PCR values from a TPM 2.0.

    On some distributions or older versions of tpm2-tools,
    the command is available as the standalone binary
    ``tpm2_pcrread`` rather than as a subcommand of ``tpm2``.
    """

    # example output:
    #   sha256:
    #     4 : 0x000000000000000000000000000000000000...
    #     7 : 0x000000000000000000000000000000000000...
    _split_hash_and_pcrs_regex = re.compile(r"(?P<hash>sha\d+):\s*(?P<pcrs>(.*\s*)*)")
    _split_pcr_index_and_value_regex = re.compile(
        r"(?P<pcr_index>\d+)\s*:\s*(?P<hash_value>0x[a-fA-F0-9]+)"
    )

    @property
    def command(self) -> str:
        return "tpm2_pcrread"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        try:
            posix_os.install_packages("tpm2-tools")
        except Exception as e:
            raise UnsupportedDistroException(
                self.node.os,
                "Failed to install tpm2-tools.",
            ) from e
        return self._check_exists()

    def read(
        self,
        pcrs: Optional[Union[int, Sequence[int]]] = None,
        algorithm: str = "sha256",
    ) -> Dict[int, str]:
        """Read PCR values from the TPM.

        A Platform Configuration Register (PCR) is a memory location in the TPM
        that stores cryptographic measurements of a system's state.

        Args:
            pcrs: PCR index or list of indices to read. If ``None``, all PCRs
                are read.
            algorithm: Hash algorithm to use (default: ``sha256``).

        Returns:
            A dictionary mapping PCR indices to their hex hash values.

        Example command/output::

            $ tpm2_pcrread sha256:4,7
              sha256:
                4 : 0x00000000...00000003
                7 : 0x00000000...00000003
        """
        pcr_list = self._get_pcr_list(pcrs)
        algorithm = algorithm.lower()
        if len(pcr_list) == 0:
            pcrs_arg = "all"
        else:
            pcrs_arg = ",".join(map(str, pcr_list))

        cmd = f"{algorithm}:{pcrs_arg}"
        cmd_result = self.run(
            cmd,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to read PCR values",
            shell=True,
            sudo=True,
            force_run=True,
        )
        output = cmd_result.stdout

        m = self._split_hash_and_pcrs_regex.search(output)
        if not m:
            raise LisaException(
                "Failed to parse tpm2_pcrread output."
                f" stdout: {output}"
                f" stderr: {cmd_result.stderr}"
            )
        hash_alg = m.group("hash")
        pcrs_info = m.group("pcrs")

        if hash_alg != algorithm:
            raise LisaException(
                f"tpm2_pcrread output contains '{hash_alg}'"
                f" instead of requested '{algorithm}'."
                f" stdout: {output}"
            )

        result: Dict[int, str] = {}
        for m in self._split_pcr_index_and_value_regex.finditer(pcrs_info):
            pcr_index = int(m.group("pcr_index"))
            hash_value = m.group("hash_value").lower()
            result[pcr_index] = hash_value

        self._log.debug(f"Parsed PCR values: {result}")
        return result

    def _get_pcr_list(self, pcrs: Optional[Union[int, Sequence[int]]]) -> List[int]:
        if pcrs is None:
            return []
        if isinstance(pcrs, int):
            return [pcrs]
        return list(pcrs)
