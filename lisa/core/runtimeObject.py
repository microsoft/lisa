from typing import Optional, cast

from lisa.common.logger import log
from lisa.core.environmentFactory import EnvironmentFactory
from lisa.core.platform import Platform
from lisa.parameter_parser.config import Config
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa.util import constants


class RuntimeObject:
    def __init__(self, config: Config):
        # global config
        self.config: Config = config
        self.platform: Optional[Platform] = None

    # do some cross object validation
    def validate(self) -> None:
        environment_config = self.config.getEnvironment()
        warn_as_error: Optional[bool] = None
        if environment_config is not None:
            warn_as_error = cast(
                Optional[bool], environment_config.get(constants.WARN_AS_ERROR)
            )
        factory = EnvironmentFactory()
        enviornments = factory.environments
        for environment in enviornments.values():
            if environment.spec is not None and isinstance(
                self.platform, ReadyPlatform
            ):
                self._validateMessage(
                    warn_as_error, "the ready platform cannot process environment spec"
                )

    def _validateMessage(
        self, warn_as_error: Optional[bool], message: str, *args: str
    ) -> None:
        if warn_as_error:
            raise Exception(message % args)
        else:
            log.warn(message, *args)
