"""LISA tests' specific configurations go here.

This file is essentially the staging ground for contributions to
`pytest-lisa`, the plugin (and package). Anything that is reusable and
stable should be sent upstream.

"""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from pytest_html.plugin import HTMLReport  # type: ignore


def pytest_html_report_title(report: HTMLReport) -> None:
    """Set HTML report title."""
    report.title = "LISAv3 Results"
