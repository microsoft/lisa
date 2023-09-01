# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from dataclasses import dataclass
from typing import Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, RemoteNode
from lisa.util import InitializableMixin, check_till_timeout, fields_to_dict, subclasses
from lisa.util.logger import get_logger
from lisa.util.shell import try_connect

from .context import get_node_context
from .schema import ReadyCheckerSchema


class ReadyChecker(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: ReadyCheckerSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.ready_checker_runbook: ReadyCheckerSchema = self.runbook
        self._log = get_logger("ready_checker", self.__class__.__name__)

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
    ) -> None:
        super().__init__(runbook=runbook)
        self.file_single_runbook: FileSingleSchema = self.runbook
        self._log = get_logger("file_single", self.__class__.__name__)

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


@dataclass_json()
@dataclass
class SshSchema(ReadyCheckerSchema):
    ...


class SshChecker(ReadyChecker):
    def __init__(
        self,
        runbook: SshSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.ssh_runbook: SshSchema = self.runbook
        self._log = get_logger("ssh", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "ssh"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SshSchema

    def is_ready(self, node: Node) -> bool:
        context = get_node_context(node)
        remote_node = cast(RemoteNode, node)
        remote_node.set_connection_info(
            **fields_to_dict(
                context.connection,
                ["address", "port", "username", "password", "private_key_file"],
            ),
        )
        self._log.debug("try to connect to the client")
        try_connect(context.connection, ssh_timeout=self.ssh_runbook.timeout)
        self._log.debug("client has been connected successfully")
        return True
