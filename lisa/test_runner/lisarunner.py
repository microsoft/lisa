from typing import cast

from lisa.core.action import ActionStatus
from lisa.core.environmentFactory import EnvironmentFactory
from lisa.core.platform import Platform
from lisa.core.testFactory import TestFactory
from lisa.core.testRunner import TestRunner
from lisa.core.testSuite import TestSuite
from lisa.util import constants
from lisa.util.logger import log


class LISARunner(TestRunner):
    def __init__(self) -> None:
        super().__init__()
        self.exitCode = None

    def getTypeName(self) -> str:
        return "LISAv2"

    def config(self, key: str, value: object) -> None:
        if key == constants.CONFIG_PLATFORM:
            self.platform: Platform = cast(Platform, value)

    async def start(self) -> None:
        await super().start()
        self.setStatus(ActionStatus.RUNNING)
        test_factory = TestFactory()
        suites = test_factory.suites

        environment_factory = EnvironmentFactory()
        platform_type = self.platform.platformType()
        # request environment
        log.info(f"platform {platform_type} environment requesting")
        environment = environment_factory.getEnvironment()
        log.info(f"platform {platform_type} environment requested")

        for suite in suites.values():
            test_object: TestSuite = suite.test_class(
                environment, list(suite.cases.keys())
            )
            await test_object.start()

        # delete enviroment after run
        log.info(f"platform {platform_type} environment {environment.name} deleting")
        self.platform.deleteEnvironment(environment)
        log.info(f"platform {platform_type} environment {environment.name} deleted")

        self.setStatus(ActionStatus.SUCCESS)

    async def stop(self) -> None:
        super().stop()

    async def cleanup(self) -> None:
        super().cleanup()
