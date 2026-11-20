# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Render PR validation recommendations without importing the LISA runtime."""

from html import escape
from typing import List, TypedDict


class ValidationRecommendation(TypedDict):
    case: str
    platform: str
    requirements: str
    reason: str
    required: bool
    execution_status: str


def recommendation_table(recommendations: List[ValidationRecommendation]) -> str:
    if not recommendations:
        return "No dedicated-platform recommendations."

    def cell(value: str) -> str:
        return (
            escape(value, quote=False)
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "<br>")
        )

    lines = [
        "| Test case | Platform | Execution | Requirements | Selection reason |",
        "|---|---|---|---|---|",
    ]
    for item in recommendations:
        status = item["execution_status"].replace("_", " ").upper()
        lines.append(
            f"| <code>{cell(item['case'])}</code> | {cell(item['platform'])} | "
            f"**{cell(status)}** | {cell(item['requirements'])} | "
            f"{cell(item['reason'])} |"
        )
    return "\n".join(lines)
