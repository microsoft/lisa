# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import Path, PurePath

# config types
CONFIG_RUNBOOK = "runbook"

RUN_ID = ""
RUN_NAME = ""

TEST_PROJECT = "test_project"
TEST_PASS = "test_pass"
TAGS = "tags"

CONCURRENCY = "concurrency"

RUNBOOK_FILE: Path
RUNBOOK_PATH: Path
RUNBOOK: str = ""
# a global cache path for all runs
CACHE_PATH: Path
# The physical path of current run.
# All logs of current run should be in this folder.
RUN_LOCAL_LOG_PATH: Path = Path()
RUN_LOCAL_WORKING_PATH: Path = Path()
# It's a pure path, which is used to create working folder in remote node.
# The datetime part of this path is the # same as local path, so it's easy to find
# remote files, which belongs to same run.
RUN_LOGIC_PATH: PurePath = PurePath()

# path related
PATH_REMOTE_ROOT = "lisa_working"
PATH_TOOL = "tool"

# patterns
GUID_REGEXP = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$|^$")
NORMALIZE_PATTERN = re.compile(r"[^A-Za-z0-9]")

# default values
DEFAULT_USER_NAME = "lisatest"

# feature names
FEATURE_DISK = "Disk"

# list types
LIST = "list"
LIST_CASE = "case"

# notifier
NOTIFIER = "notifier"
NOTIFIER_CONSOLE = "console"
NOTIFIER_FILE = "file"

# Azure Credential Type
DEFAULT_AZURE_CREDENTIAL = "default"
CERTIFICATE_CREDENTIAL = "certificate"
CLIENT_ASSERTION_CREDENTIAL = "assertion"
CLIENT_SECRET_CREDENTIAL = "secret"

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

# topologies
ENVIRONMENTS_SUBNET = "subnet"

INCLUDE = "include"
EXTENSION = "extension"
VARIABLE = "variable"

TRANSFORMER = "transformer"
TRANSFORMER_TOLIST = "tolist"

TRANSFORMER_PHASE_INIT = "init"
TRANSFORMER_PHASE_EXPANDED = "expanded"
TRANSFORMER_PHASE_ENVIRONMENT_CONNECTED = "environment_connected"
TRANSFORMER_PHASE_EXPANDED_CLEANUP = "expanded_cleanup"
TRANSFORMER_PHASE_CLEANUP = "cleanup"

COMBINATOR = "combinator"
COMBINATOR_GRID = "grid"
COMBINATOR_BATCH = "batch"
COMBINATOR_GITBISECT = "git_bisect"

ENVIRONMENT = "environment"
ENVIRONMENTS = "environments"
ENVIRONMENTS_NODES_CAPABILITY = "capability"
ENVIRONMENTS_NODES_REQUIREMENT = "requirement"
ENVIRONMENTS_NODES_REMOTE = "remote"
ENVIRONMENTS_NODES_LOCAL = "local"
ENVIRONMENTS_NODES_REMOTE_ADDRESS = "address"
ENVIRONMENTS_NODES_REMOTE_PORT = "port"
ENVIRONMENTS_NODES_REMOTE_USE_PUBLIC_ADDRESS = "use_public_address"
ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS = "public_address"
ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT = "public_port"
ENVIRONMENTS_NODES_REMOTE_USERNAME = "username"
ENVIRONMENTS_NODES_REMOTE_PASSWORD = "password"
ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE = "private_key_file"


ENVIRONMENT_KEEP_ALWAYS = "always"
ENVIRONMENT_KEEP_NO = "no"
ENVIRONMENT_KEEP_FAILED = "failed"

AVAILABILITY_DEFAULT = "default"
AVAILABILITY_NONE = "none"
AVAILABILITY_SET = "availability_set"
AVAILABILITY_ZONE = "availability_zone"

SECURITY_PROFILE_NONE = "none"
SECURITY_PROFILE_BOOT = "secureboot"
SECURITY_PROFILE_CVM = "cvm"
SECURITY_PROFILE_STATELESS = "stateless"

PLATFORM = "platform"
PLATFORM_READY = "ready"
PLATFORM_BAREMETAL = "baremetal"
PLATFORM_HYPERV = "hyperv"
PLATFORM_MOCK = "mock"

TESTCASE = "testcase"
TESTCASE_TYPE_LISA = "lisa"
TESTCASE_TYPE_LEGACY = "legacy"

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

# data disk caching type
DATADISK_CACHING_TYPE_NONE = "None"
DATADISK_CACHING_TYPE_READONLY = "ReadOnly"
DATADISK_CACHING_TYPE_READYWRITE = "ReadWrite"

DEVICE_TYPE_SRIOV = "SRIOV"
DEVICE_TYPE_NVME = "NVME"
DEVICE_TYPE_GPU = "GPU"
DEVICE_TYPE_AMD_GPU = "AMD_GPU"
DEVICE_TYPE_ASAP = "ASAP"

DISK_PERFORMANCE_TOOL_FIO = "fio"
NETWORK_PERFORMANCE_TOOL_NTTTCP = "ntttcp"
NETWORK_PERFORMANCE_TOOL_IPERF = "iperf3"
NETWORK_PERFORMANCE_TOOL_SAR = "sar"
NETWORK_PERFORMANCE_TOOL_LAGSCOPE = "lagscope"
NETWORK_PERFORMANCE_TOOL_SOCKPERF = "sockperf"
NETWORK_PERFORMANCE_TOOL_DPDK_TESTPMD = "dpdk-testpmd"

# Test for command with sudo
LISA_TEST_FOR_SUDO = "lisa test for sudo"
LISA_TEST_FOR_BASH_PROMPT = "lisa test for bash prompt"

# linux signals
SIGINT = 2
SIGTERM = 15
SIGKILL = 9
