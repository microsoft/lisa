from lisa.core.environment import Environment
from lisa.core.platform import Platform
from lisa.util import constants


class ReadyPlatform(Platform):
    @classmethod
    def platformType(cls) -> str:
        return constants.PLATFORM_READY

    def config(self, key: str, value: object) -> None:
        # ready platform has no config
        pass

    def requestEnvironmentInternal(self, environment: Environment) -> Environment:
        return environment

    def deleteEnvironmentInternal(self, environment: Environment) -> None:
        # ready platform doesn't support delete environment
        pass
