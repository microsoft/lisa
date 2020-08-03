from lisa.core.environment import Environment
from lisa.core.testsuite import TestSuite
from lisa.core.testfactory import testFactory
from lisa import ActionStatus, TestRunner, log
from lisa.util.module import import_module


class LISARunner(TestRunner):
    def __init__(self):
        super().__init__()
        self.process = None
        self.exitCode = None

    def getTypeName(self):
        return "LISAv2"

    async def start(self):
        await super().start()
        self.setStatus(ActionStatus.RUNNING)
        import_module("examples\\testsuites")
        suites = testFactory.suites
        environment = Environment()
        for suite in suites.values():
            test_object: TestSuite = suite.test_class(environment, suite.cases)
            await test_object.start()

        self.setStatus(ActionStatus.SUCCESS)

    async def stop(self):
        super().stop()
        self.process.stop()

    def cleanup(self):
        super().cleanup()
        self.process.cleanup()

    def getStatus(self):
        if self.process is not None:
            running = self.process.isRunning()
            if not running:
                self.exitCode = self.process.getExitCode()
                if self.exitCode == 0:
                    self.setStatus(ActionStatus.SUCCESS)
                else:
                    self.setStatus(ActionStatus.FAILED)
        return super().getStatus()
