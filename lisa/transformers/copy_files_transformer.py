import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Type
from lisa import constants
from dataclasses_json import dataclass_json
import glob
from lisa import LisaException, schema
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)


@dataclass_json
@dataclass
class CopyFilesTransformerSchema(DeploymentTransformerSchema):
    files: List[str] = field(default_factory=list)


class CopyFiles(DeploymentTransformer):
    @classmethod
    def type_name(cls) -> str:
        return "copy_files"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return CopyFilesTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: CopyFilesTransformerSchema = self.runbook
        if not runbook.files:
            raise LisaException("files must be defined.")

        for file in runbook.files:
            files = glob.glob(file)
            for file_path in files:
                filename = file_path.split("\\")[-1]
                if not self.node.shell.exists(
                    self.node.working_path.parent.parent / filename
                ):
                    self.node.shell.copy(
                        Path(file_path), self.node.working_path.parent.parent / filename
                    )
        return {}

    # def _find_matched_files(self, source_path: Path) -> Dict[str, FileSchema]:
    #     all_files = []
    #     for root, _, files in os.walk(source_path):
    #         for file in files:
    #             all_files.append(os.path.join(root, file))

    #     for file_map in files_map:
    #         file_path = rf"{source_path}\{file_map.source}".replace("\\", "\\\\")
    #         pattern = re.compile(
    #             file_path,
    #             re.I | re.M,
    #         )
    #         for file in all_files:
    #             if pattern.match(file):
    #                 match_files[file] = file_map
    #     return match_files
