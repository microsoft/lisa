# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
This module wraps Azure Image Testing For Linux APIs. It depends on az CLI, no
LISA or other Python dependencies. Install az CLI from here:
https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
"""
import json
import logging
import os
import subprocess
import sys
import time
from argparse import ArgumentParser, Namespace, RawTextHelpFormatter
from datetime import datetime, timezone
from typing import Any

_fmt = "%(asctime)s.%(msecs)03d[%(thread)d][%(levelname)s] %(name)s %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"
_api_version = "2023-08-01-preview"


def _generate_example(resource_type: str = "job") -> str:
    return f"""
        Examples for {resource_type.capitalize() if resource_type == 'job' else 'Job Template'}:
        Create a {resource_type}:
            python -m aitl {resource_type} create -s {{subscription_id}} -r {{resource_group}} -n {{template_name}} -b {'@./tier0.json' if resource_type == 'job' else '@./template.json'}

        List {resource_type}s:
            python -m aitl {resource_type} list -s {{subscription_id}} -r {{resource_group}}

        Get a {resource_type}:
            python -m aitl {resource_type} get -s {{subscription_id}} -r {{resource_group}} -n {{template_name}}
    """  # noqa: E501,E241


def _initialize() -> None:
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(format=_fmt, datefmt=_datefmt, level=logging.INFO)


def _execute(command: str, is_json: bool = False, check: bool = True) -> Any:
    env = os.environ.copy()
    process_result = subprocess.run(
        command, shell=True, env=env, capture_output=True, text=True, check=False
    )
    if process_result.returncode != 0:
        message = (
            f"failed to execute command: '{command}', error: {process_result.stderr}"
        )
        if check:
            raise SystemExit(message)
        else:
            logging.debug(message)
    if is_json:
        result = _parse_json(process_result.stdout)
    else:
        result = process_result.stdout

    return result


def _parse_json(content: str) -> Any:
    return json.loads(content)


def _init_arg_parser() -> Namespace:
    parser = ArgumentParser(
        prog="aitl", epilog=_generate_example(), formatter_class=RawTextHelpFormatter
    )

    sub_parser = parser.add_subparsers(dest="resource", required=True)
    _add_resource_parser(sub_parser, "job", support_update=False)
    _add_resource_parser(sub_parser, "template", support_update=True)

    return parser.parse_args()


def _add_resource_parser(
    parser: Any, resource: str, support_update: bool = False
) -> None:
    cmd_parser: ArgumentParser = parser.add_parser(
        name=resource,
        epilog=_generate_example(resource),
        formatter_class=RawTextHelpFormatter,
    )
    sub_parser = cmd_parser.add_subparsers(dest="action", required=True)

    for action in ["create", "list", "get", "delete", "update", "patch"]:
        if not support_update and action in ["update", "patch"]:
            continue

        if action == "list":
            support_name = False
        else:
            support_name = True

        if action in ["get", "delete", "update", "patch"]:
            required_name = True
        else:
            required_name = False

        action_parser = sub_parser.add_parser(
            name=action, formatter_class=RawTextHelpFormatter
        )
        _add_common_required_parsers(
            action_parser, support_name=support_name, required_name=required_name
        )

        if resource in {"job", "template"} and action in ["create", "update", "patch"]:
            _add_job_creation_parser(action_parser)

        _add_common_optional_parsers(action_parser)


def _add_job_creation_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--body",
        "-b",
        dest="body",
        default="@./tier0.json",
        help="Request body. Use @{file} to load from a file. "
        "For quoting issues in different terminals, "
        "see https://github.com/Azure/azure-",
    )


def _add_common_required_parsers(
    parser: ArgumentParser, support_name: bool = True, required_name: bool = False
) -> None:
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        help="""Set the log level output by the console to DEBUG level. By default, the
console displays logs with INFO and higher levels. The log file will
contain the DEBUG level and is not affected by this setting.
        """,
    )

    parser.add_argument(
        "--subscription_id",
        "-s",
        dest="subscription_id",
        help="subscription id",
        required=True,
    )

    parser.add_argument(
        "--resource_group",
        "-r",
        dest="resource_group",
        help="resource group name",
        required=True,
    )

    if support_name:
        parser.add_argument(
            "--name",
            "-n",
            dest="name",
            help="job or job template name",
            required=required_name,
        )


def _add_common_optional_parsers(
    parser: ArgumentParser,
) -> None:
    parser.add_argument(
        "--query",
        "-q",
        dest="query",
        help="""JMESPath to query result. See http://jmespath.org/ for more information and examples.
For example:
    Get job status: 'properties.provisioningState'
    List test results: 'properties.results[].{name:testName,status:status,message:message}'
    Summarize test results: 'properties.results[].status|{TOTAL:length(@),PASSED:length([?@==`"PASSED"`]),FAILED:length([?@==`"FAILED"`]),SKIPPED:length([?@==`"SKIPPED"`]),ATTEMPTED:length([?@==`"ATTEMPTED"`]),RUNNING:length([?@==`"RUNNING"`]),ASSIGNED:length([?@==`"ASSIGNED"`]),QUEUED:length([?@==`"QUEUED"`])}'
        """,  # noqa: E501
    )

    parser.add_argument(
        "--output",
        "-o",
        dest="output",
        help="Output format. Allowed values: json, jsonc, none, table, tsv, "
        "yaml, yamlc. Default: json",
    )

    parser.add_argument(
        "--api-version",
        "-v",
        default=_api_version,
        dest="api_version",
        help="api version",
    )

    parser.add_argument(
        "--provider",
        "-p",
        default="Microsoft.AzureImageTestingForLinux",
        dest="provider",
        help="provider name, internal use only",
    )

    parser.add_argument(
        "--endpoint",
        "-e",
        default="https://management.azure.com",
        dest="endpoint",
        help="endpoint, internal use only",
    )


def _call_rest_api(method: str, **kwargs: Any) -> Any:
    subscription_id = kwargs.pop("subscription_id")
    resource_group = kwargs.pop("resource_group")
    provider = kwargs.pop("provider")
    name = kwargs.pop("name", "")
    endpoint = kwargs.pop("endpoint")
    api_version = kwargs.pop("api_version")
    body = kwargs.pop("body", "")
    resource_type = kwargs.pop("resource")
    action = kwargs.pop("action", method.lower())
    query = kwargs.pop("query", "")
    output = kwargs.pop("output", "")

    if resource_type == "job":
        resource_type = "jobs"
    else:
        resource_type = "jobTemplates"

    resource_url = (
        f"{endpoint}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/{provider}/{resource_type}"
    )
    if name:
        resource_url = f"{resource_url}/{name}"
    resource_url = f"{resource_url}?api-version={api_version}"

    command = f"az rest --method {method} --uri {resource_url}"
    if body:
        command = f'{command} --body "{body}" --headers "Content-Type=application/json"'
    if query:
        command = f'{command} --query "{query}"'
    if output:
        command = f"{command} --output {output}"

    logging.info(f"calling REST API: {resource_url}")
    result = _execute(command=command)
    logging.info(f"called {resource_type} {action} finished.")

    if result:
        print()
        print(result)
    else:
        logging.info("no result returned, please check later.")

    return result


def _process_create_job(**kwargs: Any) -> Any:
    name: str = kwargs.get("name", "")
    if not name:
        name = datetime.now(timezone.utc).strftime("aitl_%Y%m%d_%H%M%S_%f")[:-3]
        logging.info(f"job name is not specified, generated job name: '{name}'.")
        kwargs["name"] = name

    return kwargs


if __name__ == "__main__":
    _initialize()

    cmd_args = _init_arg_parser()
    if cmd_args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    result = _execute("az account show", check=False)
    if not result:
        logging.info("not logged in, calling 'az login'...")
        _execute("az login")

    logging.debug(f"starting command with args: {cmd_args}")

    kwargs = vars(cmd_args)
    action = kwargs.get("action")
    resource = kwargs.get("resource")

    if action in ["create", "update"]:
        http_method = kwargs.pop("method", "PUT")
    elif action == "patch":
        http_method = kwargs.pop("method", "PATCH")
    elif action == "delete":
        http_method = kwargs.pop("method", "DELETE")
    else:
        http_method = kwargs.pop("method", "GET")

    method_name = f"_process_{action}_{resource}"
    self = sys.modules[__name__]
    if hasattr(self, method_name):
        logging.debug(f"calling {method_name}...")
        kwargs = getattr(self, method_name)(**kwargs)

    _call_rest_api(method=http_method, **kwargs)
