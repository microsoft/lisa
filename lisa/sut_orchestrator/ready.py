from lisa.environment import Environment
from lisa.platform_ import Platform
from lisa.util import constants
from lisa.util.logger import Logger


class ReadyPlatform(Platform):
    @classmethod
    def platform_type(cls) -> str:
        return constants.PLATFORM_READY

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if environment.runbook.nodes_requirement:
            log.warn_or_raise(
                environment.warn_as_error,
                "ready platform cannot process environment with requirement",
            )
        is_success: bool = False
        if len(environment.nodes):
            # if it has nodes, it's a good environment to run test cases
            is_success = True
        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        # do nothing for deploy
        environment.is_ready = True

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        # ready platform doesn't support delete environment
        pass
