# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from lisa.feature import Feature

FEATURE_NAME_NFS = "Nfs"


class Nfs(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_NFS

    @classmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def enabled(self) -> bool:
        raise NotImplementedError()

    def is_supported(self) -> bool:
        raise NotImplementedError()

    def create_share(self) -> None:
        raise NotImplementedError()

    def delete_share(self) -> None:
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.storage_account_name: str = ""
        self.file_share_name: str = ""
