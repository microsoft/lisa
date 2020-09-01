from lisa.environment import Environment
from lisa.platform_ import Platform
from lisa.util import constants


class ReadyPlatform(Platform):
    @classmethod
    def platform_type(cls) -> str:
        return constants.PLATFORM_READY

    def _request_environment(self, environment: Environment) -> Environment:
        return environment

    def _delete_environment(self, environment: Environment) -> None:
        # ready platform doesn't support delete environment
        pass
