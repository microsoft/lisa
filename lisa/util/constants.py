import re

# config types
CONFIG_CONFIG = "config"
CONFIG_PLATFORM = "platform"
CONFIG_TEST_CASES = "testcases"

RUN_ID = ""
RUN_NAME = ""

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
PATHS = "paths"
IS_DEFAULT = "isDefault"
ENABLE = "enable"

# by level
OPERATION_REMOVE = "remove"
OPERATION_ADD = "add"
OPERATION_OVERWRITE = "overwrite"

# typoplogies
ENVIRONMENTS_SUBNET = "subnet"

EXTENSION = "extension"

ENVIRONMENT = "environment"
ENVIRONMENTS = "environments"
ENVIRONMENTS_TEMPLATE = "template"
ENVIRONMENTS_NODES_SPEC = "spec"
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


TESTCASE = "testcase"

# test case fields
TESTCASE_CRITERIA = "criteria"
TESTCASE_CRITERIA_AREA = "area"
TESTCASE_CRITERIA_CATEGORY = "category"
TESTCASE_CRITERIA_PRIORITY = "priority"
TESTCASE_CRITERIA_TAG = "tag"

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
