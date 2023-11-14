# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.feature import Feature

FEATURE_NAME_PASSWORD_EXTENSION = "PasswordExtension"


class PasswordExtension(Feature):
    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_PASSWORD_EXTENSION

    @classmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def enabled(self) -> bool:
        raise NotImplementedError()

    def is_supported(self) -> bool:
        raise NotImplementedError()

    def reset_password(self, username: str, password: str) -> None:
        raise NotImplementedError()
