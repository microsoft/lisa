from argparse import ArgumentParser, Namespace

from lisa import commands
from lisa.util import constants


def support_config_file(parser: ArgumentParser, required: bool = True) -> None:
    parser.add_argument(
        "--config",
        "-c",
        required=required,
        dest="config",
        help="configuration file of this run",
        default="examples/runbook/hello_world.yml",
    )


def support_debug(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        help="set log level to debug",
    )


def support_variable(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--variable",
        "-v",
        dest="variables",
        action="append",
        help="define variable from command line. format is NAME:VALUE",
    )


def parse_args() -> Namespace:
    # parse args run function.
    parser = ArgumentParser()
    support_debug(parser)
    support_config_file(parser, required=False)

    subparsers = parser.add_subparsers(dest="cmd", required=False)
    run_parser = subparsers.add_parser("run")
    run_parser.set_defaults(func=commands.run)
    support_config_file(run_parser)
    support_variable(run_parser)

    list_parser = subparsers.add_parser(constants.LIST)
    list_parser.set_defaults(func=commands.list_start)
    list_parser.add_argument("--type", "-t", dest="type", choices=["case"])
    list_parser.add_argument("--all", "-a", dest="list_all", action="store_true")
    support_config_file(list_parser)
    support_variable(list_parser)

    check_parser = subparsers.add_parser("check")
    check_parser.set_defaults(func=commands.check)
    support_config_file(check_parser)
    support_variable(check_parser)

    parser.set_defaults(func=commands.run)

    for sub_parser in subparsers.choices.values():
        support_debug(sub_parser)

    args = parser.parse_args()
    return args
