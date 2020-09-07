from lisa.environment import Environment
from lisa.platform_ import Platform
from lisa.util import constants


class ReadyPlatform(Platform):
    @classmethod
    def platform_type(cls) -> str:
        return constants.PLATFORM_READY

    def _prepare_environment(self, environment: Environment) -> None:
        if environment.runbook.nodes_requirement:
            self.log.warn_or_raise(
                environment.warn_as_error,
                f"ready platform cannot process "
                f"environment [{environment.name}] with requirement",
            )
        if len(environment.nodes):
            # if it has nodes, it's a good environment
            environment.priority = 0

    def _deploy_environment(self, environment: Environment) -> None:
        # do nothing for deploy
        environment.is_ready = True

    def _delete_environment(self, environment: Environment) -> None:
        # ready platform doesn't support delete environment
        pass
