from typing import cast

from lisa.common.logger import log
from lisa.core.action import ActionStatus
from lisa.core.environment_factory import EnvironmentsFactory
from lisa.core.platform import Platform
from lisa.core.test_factory import test_factory
from lisa.core.testRunner import TestRunner
from lisa.core.testSuite import TestSuite
from lisa.util import constants


class LISARunner(TestRunner):
    def __init__(self) -> None:
        super().__init__()
        self.exitCode = None

    def getTypeName(self) -> str:
        return "LISAv2"

    def config(self, key: str, value: object) -> None:
        if key == constants.CONFIG_ENVIRONMENT_FACTORY:
            self.environmentsFactory: EnvironmentsFactory = cast(
                EnvironmentsFactory, value
            )
        elif key == constants.CONFIG_PLATFORM:
            self.platform: Platform = cast(Platform, value)

    async def start(self) -> None:
        await super().start()
        self.setStatus(ActionStatus.RUNNING)
        suites = test_factory.suites
        # request environment
        log.info("platform %s environment requesting", self.platform.platformType())
        environment = self.environmentsFactory.getEnvironment()
        log.info("platform %s environment requested", self.platform.platformType())

        for suite in suites.values():
            test_object: TestSuite = suite.test_class(
                environment, list(suite.cases.keys())
            )
            await test_object.start()

        # delete enviroment after run
        log.info("platform %s environment deleting", self.platform.platformType())
        self.platform.deleteEnvironment(environment)
        log.info("platform %s environment deleted", self.platform.platformType())

        self.setStatus(ActionStatus.SUCCESS)

    async def stop(self) -> None:
        super().stop()

    async def cleanup(self) -> None:
        super().cleanup()
