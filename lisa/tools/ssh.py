# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import shlex
from pathlib import PurePosixPath
from typing import Iterator, List

from lisa.base_tools import Cat, Sed, Service
from lisa.executable import Tool
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
        # Check well-known locations first. SUSE/SLES 16 and other modern
        # distros ship the vendor sshd_config under /usr/etc/ssh while
        # /etc/ssh/sshd_config may not exist by default.
        candidate_paths = [
            f"/etc/ssh/{file_name}",
            f"/usr/etc/ssh/{file_name}",
            f"/usr/local/etc/ssh/{file_name}",
        ]
        for path in candidate_paths:
            if self.node.shell.exists(self.node.get_pure_path(path)):
                return path
        # Fall back to a scoped find. Restrict to /etc, /usr/etc, and
        # /usr/local/etc to avoid traversing /proc, /sys, /run/user/* etc.
        # on minimal images where `find /` exits non-zero due to
        # permission-denied warnings.
        find = self.node.tools[Find]
        search_roots = ("/etc", "/usr/etc", "/usr/local/etc")
        for search_root in search_roots:
            result = find.find_files(
                self.node.get_pure_path(search_root),
                file_name,
                file_type="f",
                sudo=True,
                ignore_not_exist=True,
            )
            if result and result[0]:
                return result[0]
        raise LisaException(
            f"Could not locate '{file_name}'. Checked candidate paths "
            f"{candidate_paths} and searched under {list(search_roots)}. "
            "Verify that the OpenSSH server (sshd) package is installed "
            "on the target node and that its configuration file exists; "
            "if it lives under a non-standard prefix, update "
            "get_default_sshd_config_path() to include that location."
        )

    def set_max_session(self, count: int = 200) -> None:
        config_path = self.get_default_sshd_config_path()
        sed = self.node.tools[Sed]
        # sshd uses the first value, including values from Include directives.
        sed.insert_line_beginning(f"MaxSessions {count}", config_path, sudo=True)
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

    def get(self, setting: str, connection_context: bool = False) -> str:
        # Firstly, using command "sshd -T" to get the effective configuration
        # Take ClientAliveInterval as an example, if the value is "60m" in the config
        # file, sshd -T can show the effective value which is 3600.
        command = "sshd -T"
        if connection_context:
            connection = self.node.execute(
                "printf '%s' \"${SSH_CONNECTION:-}\"", shell=True
            ).stdout.split()
            connection_info = self.node.shell.connection_info
            username = connection_info.username
            if len(connection) != 4 or not username:
                raise LisaException(
                    "Cannot determine the active SSH connection context for "
                    "connection-specific sshd configuration"
                )
            client_address, _, server_address, server_port = connection
            context = (
                f"user={username},addr={client_address},laddr={server_address},"
                f"lport={server_port}"
            )
            command += f" -C {shlex.quote(context)}"

        result = self.node.execute(command, sudo=True)
        if result.exit_code == 0:
            # The pattern needs to match "clientaliveinterval 120"
            pattern = re.compile(
                rf"^{re.escape(setting.lower())}\s+(?P<value>.*)", re.M
            )
            matches = find_patterns_groups_in_lines(result.stdout, [pattern])
            return matches[0][0]["value"].strip() if matches[0] else ""

        self._log.warning(
            f"sshd -T failed ({result.exit_code}): {result.stderr}. "
            "Reading SSH configuration directly."
        )
        config_path = self.get_default_sshd_config_path()
        config = list(self._iter_sshd_config(PurePosixPath(config_path)))
        if connection_context and any(fields[0] == "match" for fields in config):
            raise LisaException(
                "Cannot determine connection-specific SSH settings because "
                "sshd -T -C failed and the configuration contains Match blocks"
            )
        for fields in config:
            if fields[0] == "match":
                break
            if fields[0] == setting.lower():
                return " ".join(fields[1:])
        return ""

    def _iter_sshd_config(
        self, path: PurePosixPath, depth: int = 0
    ) -> Iterator[List[str]]:
        if depth > 16:
            raise LisaException(f"SSH Include maximum depth exceeded at '{path}'")
        content = self.node.tools[Cat].read(
            shlex.quote(str(path)), force_run=True, sudo=True
        )
        for line in content.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*(?:=\s*)?(.*)$", line)
            if not match:
                raise LisaException(f"Invalid SSH configuration in '{path}': {line}")
            keyword = match[1].lower()
            arguments = shlex.split(match[2], comments=True)
            if keyword == "include":
                for pattern in arguments:
                    for included_path in self._expand_sshd_include(pattern):
                        yield from self._iter_sshd_config(included_path, depth + 1)
            else:
                yield [keyword, *arguments]

    def _expand_sshd_include(self, pattern: str) -> List[PurePosixPath]:
        path = PurePosixPath(pattern)
        if not path.is_absolute():
            path = PurePosixPath("/etc/ssh") / path
        # Quote shell syntax while retaining only pathname-expansion characters.
        shell_pattern = "".join(
            char if char in "*?[]!" else shlex.quote(char) for char in str(path)
        )
        result = self.node.execute(
            f"for config in {shell_pattern}; do "
            'if [ -e "$config" ]; then printf \'%s\\0\' "$config"; fi; done',
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Failed to expand SSH Include '{path}'",
        )
        return [
            PurePosixPath(name)
            for name in sorted(filter(None, result.stdout.split("\0")))
        ]


class Sshd(Ssh):
    @property
    def command(self) -> str:
        return "sshd"
