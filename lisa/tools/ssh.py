# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re

from lisa.base_tools import Cat, Sed, Service
from lisa.executable import Tool
from lisa.operating_system import Ubuntu
from lisa.util import LisaException, find_patterns_groups_in_lines

from .echo import Echo
from .find import Find


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
            "echo | ssh-keygen -t rsa -N ''",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on generate key files.",
        )
        cat = self.node.tools[Cat]
        public_key = cat.read(
            str(self.node.get_pure_path("$HOME/.ssh/id_rsa.pub")),
            force_run=True,
        )
        return public_key

    def enable_public_key(self, public_key: str) -> None:
        self.node.tools[Echo].write_to_file(
            public_key,
            self.node.get_pure_path("$HOME/.ssh/authorized_keys"),
            append=True,
        )

    def add_known_host(self, ip: str) -> None:
        self.node.execute(f"ssh-keyscan -H {ip} >> ~/.ssh/known_hosts", shell=True)

    def get_default_sshd_config_path(self) -> str:
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
        config_path = self.get_default_sshd_config_path()
        sed = self.node.tools[Sed]
        sed.append(f"MaxSessions {count}", config_path, sudo=True)
        service = self.node.tools[Service]
        if service.check_service_exists("sshd"):
            service.restart_service("sshd")
        elif service.check_service_exists("ssh"):
            service.restart_service("ssh")
        else:
            raise LisaException("could not find ssh or sshd service")

        # The above changes take effect only for *new* connections. So,
        # close the current connection.
        self.node.close()

    def get(self, setting: str) -> str:
        # Firstly, using command "sshd -T" to get the effective configuration
        # Take ClientAliveInterval as an example, if the value is "60m" in the config
        # file, sshd -T can show the effective value which is 3600.
        result = self.node.execute(
            f"sshd -T | grep {setting.lower()}", sudo=True, shell=True
        )
        if result.exit_code == 0:
            settings = result.stdout
            # The pattern needs to match "clientaliveinterval 120"
            pattern = re.compile(rf"^{setting.lower()}\s+(?P<value>.*)", re.M)
        else:
            config_path = self.get_default_sshd_config_path()
            settings = self.node.tools[Cat].read(config_path, True, True)
            if isinstance(self.node.os, Ubuntu):
                extra_sshd_config = "/etc/ssh/sshd_config.d/50-cloudimg-settings.conf"
                path_exist = self.node.execute(f"ls -lt {extra_sshd_config}", sudo=True)
                if path_exist.exit_code == 0:
                    settings += self.node.tools[Cat].read(extra_sshd_config, True, True)
            # The pattern needs to match: "ClientAliveInterval 120" or
            # "ClientAliveInterval 120 # this is a comment"
            pattern = re.compile(rf"^{setting}\s+(?P<value>[^#\n]*)", re.M)

        matches = find_patterns_groups_in_lines(settings, [pattern])
        if not matches[0]:
            return ""
        return (matches[0][-1])["value"]
