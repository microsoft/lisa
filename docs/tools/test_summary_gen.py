# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Update test_summary.rst with test metadata
"""

import ast
import os
from pathlib import Path
from typing import Dict, TextIO

from .doc_generator import TESTS, ClassVisitor, FuncVisitor, extract_metadata, load_path

base_path = Path(__file__).parent
table_path = (base_path / "../run_test/test_summary.rst").resolve()


def update_summary() -> None:
    """
    Updates (rewrites) test table.

    Args:
        filename (Path): the path to the test table
        test_paths (List[Path]): a list of directories containing tests
    """

    data = load_path(TESTS)
    test_paths = [(base_path / Path(x.get("value", ""))).resolve() for x in data]
    with open(table_path, "w", encoding="utf-8") as table:
        _write_title(table)

        res = []  # name, priority, platform, category, area etc.
        for test_path in test_paths:
            for root, _, files in os.walk(test_path):
                for file in files:
                    if file.endswith(".py"):
                        filename = Path(root) / file
                        tree = ast.parse(
                            filename.read_text(encoding="utf-8"), filename=str(filename)
                        )
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
        for index, node in enumerate(res, start=1):
            _update_line(table, node, index)


def _write_title(file: TextIO) -> None:
    """
    Writes the title of the test table

    Args:
        file (TextIO): test table
    """
    file.write("Test Cases\n==========\n\n")

    file.write(".. list-table::\n")
    # file.write("    :widths: 5 5 25 5 10 10 10\n")  # can be configured manually
    file.write("    :header-rows: 1\n\n")
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
    file.write(f"    * - {index}\n")  # noqa: E221
    file.write(
        f"      - :ref:`{metadata['suite_name']} <{metadata['suite_name']}>`\n"  # noqa: E221,E501
    )  # Test Suite Name
    file.write(
        f"      - :ref:`{metadata['case_name']} <{metadata['case_name']}>`\n"  # noqa: E221,E501
    )  # Test Case Name
    file.write(f"      - {metadata.get('priority', 2)}\n")  # noqa: E221
    file.write("      - Azure, Ready\n")  # Platform - defaults to both
    file.write(f"      - {metadata['category']}\n")  # noqa: E221
    file.write(f"      - {metadata['area']}\n")  # noqa: E221
