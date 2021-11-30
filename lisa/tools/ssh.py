# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools import Cat
from lisa.executable import Tool

from .echo import Echo


class Ssh(Tool):
    @property
    def command(self) -> str:
        return "ssh"

    @property
    def can_install(self) -> bool:
        return False

    def generate_key_pairs(self) -> str:
        for file in [".ssh/id_rsa.pub", ".ssh/id_rsa"]:
            file_path = self.node.get_pure_path(file)
            if self.node.shell.exists(file_path):
                self.node.shell.remove(file_path)
        self.node.execute(
            "echo | ssh-keygen -N ''",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on generate key files.",
        )
        cat = self.node.tools[Cat]
        public_key = cat.read(
            str(self.node.get_pure_path("~/.ssh/id_rsa.pub")),
            force_run=True,
        )
        return public_key

    def enable_public_key(self, public_key: str) -> None:
        self.node.tools[Echo].write_to_file(
            public_key,
            self.node.get_pure_path("~/.ssh/authorized_keys"),
            append=True,
        )
