from lisa import TestRunner
from lisa.util import Process
from lisa import ActionStatus


class LISARunner(TestRunner):
    def __init__(self):
        super().__init__()
        self.process = None
        self.exitCode = None

    def getTypeName(self):
        return "LISAv2"

    def start(self):
        self.process = Process()
        self.process.start("echo hello world")
        self.setStatus(ActionStatus.RUNNING)
        super().start()

    def stop(self):
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
