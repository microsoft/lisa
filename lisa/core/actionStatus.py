from enum import Enum


class ActionStatus(Enum):
    UNINITIALIZED = 1
    INITIALIZING = 2
    INITIALIZED = 3
    WAITING = 4
    RUNNING = 5
    SUCCESS = 6
    FAILED = 7
    STOPPING = 8
    STOPPED = 9
    UNKNOWN = 10
