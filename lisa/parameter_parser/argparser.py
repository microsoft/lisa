# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from argparse import ArgumentParser, Namespace
from pathlib import Path

from lisa import commands
from lisa.util import constants


def support_runbook(parser: ArgumentParser, required: bool = True) -> None:
    parser.add_argument(
        "--runbook",
        "-r",
        type=Path,
        required=required,
        help="Specify the path of runbook. "
        "It can be an absolute path or a relative path.",
        default=Path("examples/runbook/hello_world.yml").absolute(),
    )


def support_debug(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        help="Set the log level output by the console to DEBUG level. By default, the "
        "console displays logs with INFO and higher levels. The log file will contain "
        "the DEBUG level and is not affected by this setting.",
    )


def support_variable(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--variable",
        "-v",
        dest="variables",
        action="append",
        help="Variables are defined in runbooks, LISA doesn't pre-define any variable, "
        "Specify one or more variables in the format of `name:value`, which will "
        "overwrite the value in the YAML file. It can support secret values in the "
        "format of `s:name:value`. Learn more from documents.",
    )


def support_log_path(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--log_path",
        "-l",
        type=Path,
        dest="log_path",
        help="Uses to replace the default log root path.",
    )


def support_working_path(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--working_path",
        "-w",
        type=Path,
        dest="working_path",
        help="Uses to replace the default working path. "
        "Cache path will be created under this path.",
    )


def support_id(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--id",
        "-i",
        type=Path,
        dest="run_id",
        help="The ID is used to avoid conflicts on names or folders. If the log or "
        "name has a chance to conflict in a global storage, use an unique ID to avoid "
        "it.",
    )


def parse_args() -> Namespace:
    """This wraps Python's 'ArgumentParser' to setup our CLI."""
    parser = ArgumentParser(prog="lisa")
    support_debug(parser)
    support_runbook(parser, required=False)
    support_variable(parser)
    support_log_path(parser)
    support_working_path(parser)
    support_id(parser)

    # Default to 'run' when no subcommand is given.
    parser.set_defaults(func=commands.run)

    subparsers = parser.add_subparsers(dest="cmd", required=False)

    # Entry point for 'run'.
    run_parser = subparsers.add_parser("run")
    run_parser.set_defaults(func=commands.run)

    # Entry point for 'list-start'.
    list_parser = subparsers.add_parser(constants.LIST)
    list_parser.set_defaults(func=commands.list_start)
    list_parser.add_argument(
        "--type",
        "-t",
        dest="type",
        choices=["case"],
        help="specify the information type",
    )
    list_parser.add_argument(
        "--all",
        "-a",
        dest="list_all",
        action="store_true",
        help="ignore test case selection, and display all test cases",
    )

    # Entry point for 'check'.
    check_parser = subparsers.add_parser("check")
    check_parser.set_defaults(func=commands.check)

    for sub_parser in subparsers.choices.values():
        support_runbook(sub_parser)
        support_variable(sub_parser)
        support_debug(sub_parser)

    return parser.parse_args()
