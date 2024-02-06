# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import dataclass_json

from lisa import schema


@dataclass_json
@dataclass
class HypervServer:
    address: str
    username: str
    password: str


@dataclass_json
@dataclass
class ExtraArgs:
    command: str
    args: str


@dataclass_json()
@dataclass
class VHDSourceSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    pass


@dataclass_json()
@dataclass
class LocalVHDSourceSchema(VHDSourceSchema):
    vhd_path: str = ""
    extract: bool = False


@dataclass_json
@dataclass
class HypervPlatformSchema:
    vhd_source: VHDSourceSchema
    servers: List[HypervServer] = field(default_factory=list)
    extra_args: List[ExtraArgs] = field(default_factory=list)


@dataclass_json
@dataclass
class VhdSchema(schema.ImageSchema):
    vhd_path: Optional[str] = None


@dataclass_json
@dataclass
class HypervNodeSchema:
    hyperv_generation: int = 2
    vhd: Optional[VhdSchema] = None
    osdisk_size_in_gb: int = 30
