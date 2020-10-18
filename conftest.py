"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from pathlib import Path

from _pytest.config.argparsing import Parser

pytest_plugins = "node_plugin"


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook for adding arbitrary CLI options.

    https://docs.pytest.org/en/latest/example/simple.html

    """
    parser.addoption(
        "--keep-vms",
        action="store_true",
        default=False,
        help="Keeps deployed VMs cached between test runs, useful for developers.",
    )
    # TODO: Add “--lisa” (and “--debug” etc.) options which set up our
    # defaults, instead of encoding them in the Makefile


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"


LINUX_SCRIPTS = Path("../Testscripts/Linux")
