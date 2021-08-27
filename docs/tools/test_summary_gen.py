# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Update test_summary.rst with test metadata
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, TextIO

from doc_generator import (  # type: ignore
    TESTS,
    ClassVisitor,
    FuncVisitor,
    extract_metadata,
    load_path,
)

base_path = Path(__file__).parent
table_path = (base_path / "../run_test/test_summary.rst").resolve()


def update_summary(filename: Path, test_paths: List[Path]) -> None:
    """
    Updates (rewrites) test table.

    Args:
        filename (Path): the path to the test table
        test_paths (List[Path]): a list of directories containing tests
    """
    with open(table_path, "w") as table:
        _write_title(table)

        index = 0
        res = []  # name, priority, platform, category, area etc.
        for test_path in test_paths:
            for root, _, files in os.walk(test_path):
                for file in files:
                    if file.endswith(".py"):
                        # print("Processing " + file)
                        filename = Path(root) / file
                        with open(filename, "r") as f:
                            contents = f.read()
                            tree = ast.parse(contents)
                        cls_visitor = ClassVisitor()
                        func_visitor = FuncVisitor()
                        cls_visitor.visit(tree)
                        func_visitor.visit(tree)

                        for case in extract_metadata(func_visitor.get_cases()):
                            case["case_name"] = case["name"]
                            del case["name"]
                            for suite in extract_metadata(cls_visitor.get_suites()):
                                suite["suite_name"] = suite["name"]
                                del suite["name"]
                                res.append({**suite, **case})  # merge two dicts
        for node in res:
            index += 1
            _update_line(table, node, index)


def _write_title(file: TextIO) -> None:
    """
    Writes the title of the test table

    Args:
        file (TextIO): test table
    """
    link = "https://github.com/microsoft/lisa/blob/master/Documents/LISAv2-TestCase-Statistics.md"  # noqa: E501
    title = "Test Cases"
    file.write(title + "\n")
    file.write("=" * len(title) + "\n")
    file.write("\n")

    file.write(".. seealso::\n")
    file.write("    `LISAv2 Tests <" + link + ">`__\n")
    file.write("\n")

    file.write(".. warning::\n")
    file.write("\n")
    file.write("    |:construction:| WIP |:construction:|\n")
    file.write("\n")

    file.write(".. list-table::\n")
    # file.write("    :widths: 5 5 25 5 10 10 10\n")  # can be configured manually
    file.write("    :header-rows: 1\n")
    file.write("\n")

    file.write("    * - Index\n")
    file.write("      - Test Suite Name\n")
    file.write("      - Test Case Name\n")
    file.write("      - Priority\n")
    file.write("      - Platform\n")
    file.write("      - Category\n")
    file.write("      - Area\n")


def _update_line(file: TextIO, metadata: Dict[str, str], index: int) -> None:
    """
    Writes a row in test table.

    Args:
        file (TextIO): test table
        metadata (Dict[str, str]): test case metadata
        index (int): no.# of test case
    """
    file.write("    * - " + str(index) + "\n")  # Index
    file.write(
        "      - "
        + ":ref:`"
        + metadata["suite_name"]
        + " <"
        + metadata["suite_name"]
        + ">`\n"
    )  # Test Suite Name
    file.write(
        "      - "
        + ":ref:`"
        + metadata["case_name"]
        + " <"
        + metadata["case_name"]
        + ">`\n"
    )  # Test Case Name
    file.write("      - " + str(metadata["priority"]) + "\n")  # Priority
    file.write("      - " + "Azure, Ready" + "\n")  # Platform - defaults to both
    file.write("      - " + metadata["category"] + "\n")  # Category
    file.write("      - " + metadata["area"] + "\n")  # Area


if __name__ == "__main__":
    data = load_path(TESTS)
    test_paths = [(base_path / Path(x.get("value"))).resolve() for x in data]

    update_summary(table_path, test_paths)
