# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools import Cat, Sed
from lisa.executable import Tool
from lisa.util import LisaException

from .echo import Echo
from .find import Find
from .service import Service


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

    def add_known_host(self, ip: str) -> None:
        self.node.execute(f"ssh-keyscan -H {ip} >> ~/.ssh/known_hosts", shell=True)

    def get_sshd_config_path(self) -> str:
        file_name = "sshd_config"
        default_path = f"/etc/ssh/{file_name}"
        if self.node.shell.exists(self.node.get_pure_path(default_path)):
            return default_path
        find = self.node.tools[Find]
        result = find.find_files(self.node.get_pure_path("/"), file_name, sudo=True)
        if result and result[0]:
            return result[0]
        else:
            raise LisaException("not find sshd_config")

    def set_max_session(self, count: int = 200) -> None:
        config_path = self.get_sshd_config_path()
        sed = self.node.tools[Sed]
        sed.append(f"MaxSessions {count}", config_path, sudo=True)
        service = self.node.tools[Service]
        service.restart_service("sshd")
