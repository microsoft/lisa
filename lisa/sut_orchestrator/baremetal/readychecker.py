# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Type, cast

import paramiko
import requests
from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, RemoteNode
from lisa.util import InitializableMixin, LisaException, check_till_timeout, subclasses
from lisa.util.logger import Logger, get_logger
from lisa.util.shell import try_connect

from .context import get_node_context
from .schema import ReadyCheckerSchema


class ReadyChecker(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: ReadyCheckerSchema,
        parent_logger: Logger,
    ) -> None:
        super().__init__(runbook=runbook)
        self.ready_checker_runbook: ReadyCheckerSchema = self.runbook
        self._log = get_logger(
            "ready_checker", self.__class__.__name__, parent=parent_logger
        )

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ReadyCheckerSchema

    def clean_up(self) -> None:
        pass

    def prepare(self, node: Node) -> None:
        pass

    def is_ready(self, node: Node) -> bool:
        return False


@dataclass_json()
@dataclass
class FileSingleSchema(ReadyCheckerSchema):
    file: str = ""


class FileSingleChecker(ReadyChecker):
    def __init__(
        self,
        runbook: FileSingleSchema,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook=runbook, **kwargs)
        self.file_single_runbook: FileSingleSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "file_single"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return FileSingleSchema

    def clean_up(self) -> None:
        if os.path.exists(self.file_single_runbook.file):
            os.remove(self.file_single_runbook.file)
            self._log.debug(
                f"The file {self.file_single_runbook.file} has been removed"
            )
        else:
            self._log.debug(
                f"The file {self.file_single_runbook.file} does not exist,"
                " so it doesn't need to be cleaned up."
            )

    def is_ready(self, node: Node) -> bool:
        check_till_timeout(
            lambda: os.path.exists(self.file_single_runbook.file) is True,
            timeout_message="wait for ready check ready",
            timeout=self.file_single_runbook.timeout,
        )
        return os.path.exists(self.file_single_runbook.file)


class SshChecker(ReadyChecker):
    def __init__(
        self,
        runbook: ReadyCheckerSchema,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook=runbook, **kwargs)
        self.ssh_runbook: ReadyCheckerSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "ssh"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ReadyCheckerSchema

    def _configure_connection(self, node: Node) -> schema.ConnectionInfo:
        context = get_node_context(node)
        remote_node = cast(RemoteNode, node)

        assert context.client.connection, "connection is required for ssh checker"
        connection = context.client.connection
        remote_node.set_connection_info(
            address=connection.address,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            private_key_file=connection.private_key_file,
            use_public_address=False,
        )
        return connection.get_connection_info(is_public=False)

    def is_ready(self, node: Node) -> bool:
        connection_info = self._configure_connection(node)
        self._log.debug(f"try to connect to client: {node}")
        try_connect(
            connection_info,
            ssh_timeout=self.ssh_runbook.timeout,
        )
        self._log.debug("client has been connected successfully")
        return True


class SshFreshInstallChecker(SshChecker):
    def __init__(self, runbook: ReadyCheckerSchema, **kwargs: Any) -> None:
        super().__init__(runbook=runbook, **kwargs)
        if self.ssh_runbook.timeout <= 0:
            raise LisaException("Fresh-install readiness timeout must be positive")
        self._previous_root_uuids: Dict[int, str] = {}

    @classmethod
    def type_name(cls) -> str:
        return "ssh_fresh_install"

    def _read_root_uuid(self, node: Node) -> str:
        context = get_node_context(node)
        if context.client.connection is None:
            raise LisaException("A connection is required to verify a fresh install")
        connection = context.client.connection.get_connection_info(is_public=False)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())
        try:
            # Do not initialize the test node's OS/tool cache from the old image.
            client.connect(
                hostname=connection.address,
                port=connection.port,
                username=connection.username,
                password=connection.password,
                key_filename=connection.private_key_file,
                timeout=10,
                auth_timeout=10,
                banner_timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            stdin, stdout, stderr = client.exec_command(
                "sudo -n findmnt --noheadings --output UUID --target /",
                timeout=10,
            )
            stdin.close()
            raw_output = stdout.read()
            raw_error = stderr.read()
            if not isinstance(raw_output, bytes) or not isinstance(raw_error, bytes):
                raise LisaException("Unexpected SSH response while reading root UUID")
            output = raw_output.decode("utf-8", errors="replace")
            error = raw_error.decode("utf-8", errors="replace")
            check_till_timeout(
                lambda: stdout.channel.exit_status_ready(),
                timeout_message="wait for SSH command exit status",
                timeout=10,
                interval=1,
            )
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                raise LisaException(
                    "Cannot read the Linux root filesystem UUID. "
                    "The fresh-install checker requires findmnt and noninteractive "
                    f"sudo. Exit code: {exit_code}; stdout: {output}; stderr: {error}"
                )
            if error:
                self._log.info(f"Root filesystem UUID probe stderr: {error}")
            root_uuid = output.strip().lower()
            if len(root_uuid) < 8 or not re.fullmatch(
                r"[0-9a-f]+(?:-[0-9a-f]+)*", root_uuid
            ):
                raise LisaException(
                    f"Cannot verify a unique root filesystem UUID: {output!r}"
                )
            return root_uuid
        finally:
            client.close()

    def prepare(self, node: Node) -> None:
        try:
            previous = self._read_root_uuid(node)
        except (OSError, EOFError, paramiko.SSHException, LisaException) as error:
            raise LisaException(
                "Cannot establish the pre-install root filesystem identity; "
                f"refusing an unverifiable reimage: {error}"
            ) from error
        self._previous_root_uuids[node.index] = previous
        self._log.info(f"Pre-install root filesystem UUID: {previous}")

    def is_ready(self, node: Node) -> bool:
        if node.index not in self._previous_root_uuids:
            raise LisaException(
                "Fresh-install readiness was not prepared before deployment"
            )
        previous = self._previous_root_uuids[node.index]
        last_observation = "no post-install identity obtained"

        def _root_changed() -> bool:
            nonlocal last_observation
            try:
                current = self._read_root_uuid(node)
            except paramiko.AuthenticationException as error:
                raise LisaException(
                    f"Post-install SSH authentication failed: {error}"
                ) from error
            except (OSError, EOFError, paramiko.SSHException, LisaException) as error:
                last_observation = str(error)
                self._log.debug(f"Waiting for a verifiable installed OS: {error}")
                return False
            last_observation = f"root UUID {current}"
            if current == previous:
                raise LisaException(
                    f"SSH connected to the pre-install root filesystem {previous}; "
                    "the ISO did not provide a fresh installation"
                )
            self._log.info(f"Verified new root filesystem UUID: {current}")
            return True

        try:
            check_till_timeout(
                _root_changed,
                timeout_message="wait for a verified fresh OS installation",
                timeout=self.ssh_runbook.timeout,
                interval=5,
            )
        except LisaException as error:
            raise LisaException(
                f"Fresh installation was not verified. Pre-install root UUID: "
                f"{previous}; last observation: {last_observation}. {error}"
            ) from error
        self._configure_connection(node)
        return True


@dataclass_json()
@dataclass
class HttpSchema(ReadyCheckerSchema):
    # http://ip/client.ip
    url: str = ""
    # http://ip/cleanup.php, it contains the logic to remove the client.ip
    cleanup_url: str = ""


class HttpChecker(ReadyChecker):
    def __init__(
        self,
        runbook: HttpSchema,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook=runbook, **kwargs)
        self.http_check_runbook: HttpSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "http"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HttpSchema

    def clean_up(self) -> None:
        if self.http_check_runbook.cleanup_url:
            # in cleanup_url, it contains the logic to remove file
            # which is the flag of client ready
            response = requests.get(self.http_check_runbook.cleanup_url, timeout=20)
            if response.status_code == 200:
                self._log.debug(
                    f"The url {self.http_check_runbook.url} has been removed"
                )
            else:
                raise LisaException(
                    f"Failed to remove url {self.http_check_runbook.url}"
                )

    def is_ready(self, node: Node) -> bool:
        check_till_timeout(
            lambda: (requests.get(self.http_check_runbook.url, timeout=2)).status_code
            == 200,
            timeout_message=f"wait for {self.http_check_runbook.url} ready",
            timeout=self.http_check_runbook.timeout,
        )
        return True
