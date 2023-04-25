# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_RESET_PASSWORD = "ResetPassword"


class ResetPassword(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_RESET_PASSWORD

    @classmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def enabled(self) -> bool:
        raise NotImplementedError()

    def is_supported(self) -> bool:
        raise NotImplementedError()

    def reset_password(self, username: str, password: str) -> None:
        raise NotImplementedError()
