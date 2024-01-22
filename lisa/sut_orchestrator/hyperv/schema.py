# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import List

from dataclasses_json import dataclass_json


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


@dataclass_json
@dataclass
class HypervPlatformSchema:
    servers: List[HypervServer] = field(default_factory=list)
    extra_args: List[ExtraArgs] = field(default_factory=list)


@dataclass_json
@dataclass
class HypervNodeSchema:
    hyperv_generation: int = 2
    vhd: str = ""
    osdisk_size_in_gb: int = 30
