# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import KeyLoaderSchema


class KeyLoader(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: KeyLoaderSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.key_loader_runbook: KeyLoaderSchema = self.runbook
        self._log = get_logger("key_loader", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return KeyLoaderSchema

    def load_key(self, sources_path: List[Path]) -> str:
        raise NotImplementedError()


@dataclass_json()
@dataclass
class BuildSchema(KeyLoaderSchema):
    file: str = ""
    pattern: str = "id_rsa.*"


class BuildLoader(KeyLoader):
    def __init__(
        self,
        runbook: BuildSchema,
    ) -> None:
        super().__init__(runbook=runbook)
        self.key_file_runbook: BuildSchema = self.runbook
        self._log = get_logger("build", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "build"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BuildSchema

    def load_key(self, sources_path: List[Path]) -> str:
        pattern = re.compile(
            self.key_file_runbook.pattern,
            re.I | re.M,
        )
        for source_path in sources_path:
            for filename in os.listdir(source_path):
                if pattern.match(filename):
                    return os.path.join(source_path, filename)
        return ""
