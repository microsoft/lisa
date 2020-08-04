from argparse import ArgumentParser
from lisa import command_entries


def support_config_file(parser: ArgumentParser, required=True):
    parser.add_argument(
        "--config",
        "-c",
        required=required,
        dest="config",
        help="configuration file of this run",
        default="examples/runbook/hello_world.yml",
    )


def support_debug(parser: ArgumentParser):
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        help="set log level to debug",
    )


def support_variable(parser: ArgumentParser):
    parser.add_argument(
        "--variable",
        "-v",
        dest="variables",
        action="append",
        help="define variable from command line. format is NAME:VALUE",
    )


def parse_args():
    # parse args run function.
    parser = ArgumentParser()
    support_debug(parser)
    support_config_file(parser, required=False)

    subparsers = parser.add_subparsers(dest="cmd", required=False)
    run_parser = subparsers.add_parser("run")
    run_parser.set_defaults(func=command_entries.run)
    support_config_file(run_parser)
    support_variable(run_parser)

    list_parser = subparsers.add_parser("list")
    list_parser.set_defaults(func=command_entries.list_start)
    support_config_file(list_parser)
    support_variable(list_parser)

    check_parser = subparsers.add_parser("check")
    check_parser.set_defaults(func=command_entries.check)
    support_config_file(check_parser)
    support_variable(check_parser)

    parser.set_defaults(func=command_entries.run)

    for sub_parser in subparsers.choices.values():
        support_debug(sub_parser)

    args = parser.parse_args()
    return args
