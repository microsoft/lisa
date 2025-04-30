# A Debugger class is a generic class in LISA that provides a framework for debugging
#  by executing commands in a VM (using LISA Tools) or by using Platform APIs (LISA Features)
#  or by running anything on the Orchestrator that executes LISA.
# A Debugger can be invoked before a LISA Test, after a LISA Test, or during a LISA Test.
# The DebuggerManager registers the Debugger class to a testcase and tracks the lifecycle of the testcase.
# The DebuggerManager invokes the Debugger class according to the lifecycle of the testcase.
from lisa.messages import TestStatus
from lisa.testsuite import TestResult


class DebuggerManager:
    def __init__(self, test_result: TestResult):
        self.test_result = test_result
        self.debuggers: list = []
        self.triggers: dict[Triggers: Debugger] = defaultdict(list)

    def register_debugger(self, debugger: Debugger, triggers: list):
        # trigger can be 'before', 'during', 'failed'
        self.debuggers.append(debugger)
        for trigger in triggers:
            self.triggers[trigger].append(debugger)

    def unregister_debugger(self, debugger):
        for i in range(len(self.debuggers)):
            if self.debuggers[i] == debugger:
                del self.debuggers[i]
                break

    def trigger_debugger(self, trigger):
        for trigger in self.triggers[trigger]:
            # check if debugger is run once or run at interval, if it is run at interval keep triggering based on schedule and max count
            if trigger.run_schema.run_type == 'run_once':
                trigger.run(trigger, self.test_result)
                self.unregister_debugger(trigger)
            elif trigger.run_schema.run_type == 'run_at_interval':
                # track run count and run according to schedule
                pass

# Run schema defines if the debugger should runonce, runatinterval
# and if runatinterval, how often it should run
# and maximum number of times it should run
class RunSchema:
    def __init__(self, run_type, schedule, max_run: int = 0):
        self.run_type = # one of run_once, run_at_interval
        self.schedule = schedule
        self.max_run = max_run

# Debugger 
class Debugger:
    def __init__(self, name, environment, run_schema: RunSchema):
        self.environment = environment
        self.name = name
        self.run_schema = run_schema
        self.run_count = 0


    def run(self, trigger,  state: TestStatus):
        # Use tools, feature, other exisiting ways to debug SUT or Orchestrator VM
        pass
