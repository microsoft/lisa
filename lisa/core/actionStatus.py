from enum import Enum

ActionStatus = Enum(
    "ActionStatus",
    [
        "UNINITIALIZED",
        "INITIALIZING",
        "INITIALIZED",
        "WAITING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
        "STOPPING",
        "STOPPED",
        "UNKNOWN",
    ],
)
