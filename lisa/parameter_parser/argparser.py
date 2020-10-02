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
        help="Path to the runbook",
        default=Path("examples/runbook/hello_world.yml").absolute(),
    )


def support_debug(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        help="Set log level to debug",
    )


def support_variable(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--variable",
        "-v",
        dest="variables",
        action="append",
        help="Define one or more variables with 'NAME:VALUE'",
    )


def parse_args() -> Namespace:
    """This wraps Python's 'ArgumentParser' to setup our CLI."""
    parser = ArgumentParser()
    support_debug(parser)
    support_runbook(parser, required=False)
    support_variable(parser)

    # Default to ‘run’ when no subcommand is given.
    parser.set_defaults(func=commands.run)

    subparsers = parser.add_subparsers(dest="cmd", required=False)

    # Entry point for ‘run’.
    run_parser = subparsers.add_parser("run")
    run_parser.set_defaults(func=commands.run)

    # Entry point for ‘list-start’.
    list_parser = subparsers.add_parser(constants.LIST)
    list_parser.set_defaults(func=commands.list_start)
    list_parser.add_argument("--type", "-t", dest="type", choices=["case"])
    list_parser.add_argument("--all", "-a", dest="list_all", action="store_true")

    # Entry point for ‘check’.
    check_parser = subparsers.add_parser("check")
    check_parser.set_defaults(func=commands.check)

    for sub_parser in subparsers.choices.values():
        support_runbook(sub_parser)
        support_variable(sub_parser)
        support_debug(sub_parser)

    return parser.parse_args()
