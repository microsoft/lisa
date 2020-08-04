from lisa.parameter_parser.config import Config
from lisa.common.logger import log
from lisa import Platform, Environment
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa import constants


class RuntimeObject:
    def __init__(self, config: Config):
        # global config
        self.config: Config = config
        self.environment: Environment = None
        self.platform: Platform = None

    # do some cross object validation
    def validate(self):
        environment_config = self.config.getEnvironment()
        warn_as_error = None
        if environment_config is not None:
            warn_as_error = environment_config[constants.WARN_AS_ERROR]
        if self.environment.spec is not None and isinstance(
            self.platform, ReadyPlatform
        ):
            self._validateMessage(
                warn_as_error, "environment spec won't be processed by ready platform."
            )

    def _validateMessage(self, warn_as_error: bool, message, *args):
        if warn_as_error:
            raise Exception(message % args)
        else:
            log.warn(message, *args)
