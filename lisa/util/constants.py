import re
from pathlib import Path, PurePath

# config types
CONFIG_RUNBOOK = "runbook"

RUN_ID = ""
RUN_NAME = ""

RUNBOOK_PATH: Path
CACHE_PATH: Path
RUN_LOCAL_PATH: Path = Path()
RUN_LOGIC_PATH: PurePath = PurePath()

# path related
PATH_REMOTE_ROOT = "lisa_working"
PATH_TOOL = "tool"

# patterns
GUID_REGEXP = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$")
NORMALIZE_PATTERN = re.compile(r"[^\w\d]")

# list types
LIST = "list"
LIST_CASE = "case"

# common
NODES = "nodes"
NAME = "name"
TYPE = "type"
IS_DEFAULT = "isDefault"
ENABLE = "enable"

# by level
OPERATION_REMOVE = "remove"
OPERATION_ADD = "add"
OPERATION_OVERWRITE = "overwrite"

# typoplogies
ENVIRONMENTS_SUBNET = "subnet"

EXTENSION = "extension"
VARIABLE = "variable"

ENVIRONMENT = "environment"
ENVIRONMENTS = "environments"
ENVIRONMENTS_NODES_CAPABILITY = "capability"
ENVIRONMENTS_NODES_REQUIREMENT = "requirement"
ENVIRONMENTS_NODES_REMOTE = "remote"
ENVIRONMENTS_NODES_LOCAL = "local"
ENVIRONMENTS_NODES_REMOTE_ADDRESS = "address"
ENVIRONMENTS_NODES_REMOTE_PORT = "port"
ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS = "public_address"
ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT = "public_port"
ENVIRONMENTS_NODES_REMOTE_USERNAME = "username"
ENVIRONMENTS_NODES_REMOTE_PASSWORD = "password"
ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE = "private_key_file"

PLATFORM = "platform"
PLATFORM_READY = "ready"
PLATFORM_MOCK = "mock"

TESTCASE = "testcase"

# test case fields
TESTCASE_CRITERIA = "criteria"
TESTCASE_CRITERIA_AREA = "area"
TESTCASE_CRITERIA_CATEGORY = "category"
TESTCASE_CRITERIA_PRIORITY = "priority"
TESTCASE_CRITERIA_TAGS = "tags"

TESTCASE_SELECT_ACTION = "select_action"
TESTCASE_SELECT_ACTION_NONE = "none"
TESTCASE_SELECT_ACTION_INCLUDE = "include"
TESTCASE_SELECT_ACTION_EXCLUDE = "exclude"
TESTCASE_SELECT_ACTION_FORCE_INCLUDE = "forceInclude"
TESTCASE_SELECT_ACTION_FORCE_EXCLUDE = "forceExclude"

TESTCASE_TIMES = "times"
TESTCASE_RETRY = "retry"
TESTCASE_USE_NEW_ENVIRONMENT = "use_new_environment"
TESTCASE_IGNORE_FAILURE = "ignore_failure"
