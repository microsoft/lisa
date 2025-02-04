# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from dataclasses import dataclass
from typing import Any, Type, cast

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

    def is_ready(self, node: Node) -> bool:
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
        self._log.debug(f"try to connect to client: {node}")
        try_connect(
            connection.get_connection_info(is_public=False),
            ssh_timeout=self.ssh_runbook.timeout,
        )
        self._log.debug("client has been connected successfully")
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
