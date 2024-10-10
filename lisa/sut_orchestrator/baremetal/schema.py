# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from typing import Any, List, Optional

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.util import field_metadata


@dataclass_json()
@dataclass
class ClientCapabilities:
    core_count: int = field(default=-1)
    free_memory_mb: int = field(default=-1)


@dataclass_json()
@dataclass
class ClientSchema:
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    capabilities: Optional[ClientCapabilities] = None


@dataclass_json()
@dataclass
class RackManagerClientSchema(ClientSchema):
    management_port: Optional[int] = field(default=-1)


@dataclass_json()
@dataclass
class IdracClientSchema(ClientSchema):
    iso_http_url: Optional[str] = field(default="")


@dataclass_json()
@dataclass
class ReadyCheckerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="file_single", metadata=field_metadata(required=True))
    timeout: int = 300


@dataclass_json()
@dataclass
class FileSchema:
    source: str = field(default="")
    destination: Optional[str] = field(default="")


@dataclass_json()
@dataclass
class BuildSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="smb", metadata=field_metadata(required=True))
    name: str = ""
    share: str = ""
    files: List[FileSchema] = field(default_factory=list)


@dataclass_json()
@dataclass
class IpGetterSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="file_single", metadata=field_metadata(required=True))


@dataclass_json()
@dataclass
class KeyLoaderSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="build", metadata=field_metadata(required=True))


@dataclass_json()
@dataclass
class BootConfigSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="boot_config", metadata=field_metadata(required=True))


@dataclass_json()
@dataclass
class ClusterSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="rackmanager", metadata=field_metadata(required=True))
    build: Optional[BuildSchema] = None
    ready_checker: Optional[ReadyCheckerSchema] = None
    ip_getter: Optional[IpGetterSchema] = None
    key_loader: Optional[KeyLoaderSchema] = None
    boot_config: Optional[BootConfigSchema] = None


@dataclass_json()
@dataclass
class SourceSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    type: str = field(default="ado", metadata=field_metadata(required=True))
    name: str = ""


@dataclass_json()
@dataclass
class Artifact:
    artifact_name: str = ""
    extract: bool = True


@dataclass_json()
@dataclass
class ADOSourceSchema(SourceSchema):
    organization_url: str = field(default="", metadata=field_metadata(required=True))
    project: str = field(default="", metadata=field_metadata(required=True))
    build_id: int = 0
    pipeline_name: str = ""
    pat: str = field(default="", metadata=field_metadata(required=True))
    artifacts: List[Artifact] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.organization_url:
            raise ValueError("organization_url cannot be empty")
        if not self.project:
            raise ValueError("project cannot be empty")
        if not self.pat:
            raise ValueError("pat cannot be empty")
        if not self.artifacts:
            raise ValueError("artifacts cannot be empty")
        if not self.build_id and not self.pipeline_name:
            raise ValueError("build_id and pipeline_name are both empty")
        add_secret(self.pat)


@dataclass_json()
@dataclass
class SMBBuildSchema(BuildSchema):
    username: str = ""
    password: str = ""
    share: str = ""
    server_name: str = ""

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.username, PATTERN_HEADTAIL)
        add_secret(self.password)


@dataclass_json()
@dataclass
class TftpBuildSchema(BuildSchema):
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.connection and self.connection.password:
            add_secret(self.connection.password)


@dataclass_json()
@dataclass
class IdracSchema(ClusterSchema):
    address: str = ""
    username: str = ""
    password: str = ""
    client: List[IdracClientSchema] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.username, PATTERN_HEADTAIL)
        add_secret(self.password)


@dataclass_json()
@dataclass
class RackManagerSchema(ClusterSchema):
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    client: List[RackManagerClientSchema] = field(default_factory=list)


@dataclass_json()
@dataclass
class BareMetalPlatformSchema:
    source: Optional[SourceSchema] = field(default=None)
    cluster: List[ClusterSchema] = field(default_factory=list)
