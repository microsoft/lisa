# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Update test_spec.rst with test metadata
"""

import ast
import contextlib
import os
from pathlib import Path
from typing import Dict, TextIO

from .doc_generator import TESTS, ClassVisitor, FuncVisitor, extract_metadata, load_path

base_path = Path(__file__).parent
file_path = (base_path / "../run_test/test_spec.rst").resolve()  # path of test_spec.rst


def update_file() -> None:
    """
    Updates (rewrites) test specifications.

    Args:
        filename (Path): the path to the test spec
        test_paths (List[Path]): a list of directories containing tests
    """
    data = load_path(TESTS)
    test_paths = [(base_path / Path(x.get("value", ""))).resolve() for x in data]

    with open(file_path, "w", encoding="utf-8") as test_spec:
        _write_title(test_spec)

        for test_path in test_paths:
            for root, _, files in os.walk(test_path):
                for file in files:
                    if file.endswith(".py"):
                        test_name = Path(root) / file
                        tree = ast.parse(
                            test_name.read_text(encoding="utf-8"),
                            filename=str(test_name),
                        )
                        cls_visitor = ClassVisitor()
                        func_visitor = FuncVisitor()
                        cls_visitor.visit(tree)
                        func_visitor.visit(tree)

                        for suite in extract_metadata(cls_visitor.get_suites()):
                            _write_suite(test_spec, suite)
                            for case in extract_metadata(func_visitor.get_cases()):
                                _write_case(test_spec, case, suite["name"])


def _write_title(file: TextIO) -> None:
    """
    Writes the title of test specifications

    Args:
        file (TextIO): test spec file
    """
    file.write("Test Specification\n==================\n\n")
    file.write("This file lists all test cases' specifications.\n\n")


def _write_suite(file: TextIO, metadata: Dict[str, str]) -> None:
    """
    Writes info of a test suite.

    Args:
        file (TextIO): test spec file
        metadata (Dict[str, str]): test suite metadata
    """
    file.write(f".. _{metadata['name']}:\n\n")  # custom anchor
    file.write(f".. class:: {metadata['name']}\n")  # Test Suite Name
    file.write("    :noindex:\n\n")

    _write_description(file, metadata, True)  # Description

    file.write("    :platform: ``Azure, Ready``\n")  # Platform
    file.write(f"    :area: ``{metadata['area']}``\n")  # Area

    if metadata["category"]:
        file.write(f"    :category: ``{metadata['category']}``\n\n")  # Category


def _write_case(file: TextIO, metadata: Dict[str, str], suite_name: str = "") -> None:
    """
    Writes info of a test case.

    Args:
        file (TextIO): test spec file
        metadata (Dict[str, str]): test case metadata
        suite_name (str): name of the parent test suite
    """
    # Create unique anchor by combining suite and case name if suite is provided
    anchor_name = f"{suite_name}_{metadata['name']}" if suite_name else metadata["name"]
    file.write(f".. _{anchor_name}:\n\n")  # custom anchor
    file.write(f"    .. method:: {metadata['name']}\n")  # Test Case Name
    file.write("        :noindex:\n\n")

    file.write("    ")  # 1-tab indentation
    _write_description(file, metadata)  # Description

    file.write(f"        :priority: ``{metadata.get('priority', 2)}``\n")  # Priority

    if "requirement" in metadata:
        file.write(f"        :requirement: ``{metadata['requirement']}``\n")

    file.write("\n")


def _write_description(
    file: TextIO, metadata: Dict[str, str], is_suite: bool = False
) -> None:
    """
    Writes the description of a test suite/case.

    Args:
        file (TextIO): test spec file
        metadata (Dict[str, str]): test suite/case metadata
        is_suite (bool): signifies if it's a test suite. Defaults to False.
    """
    file.write("    :description: | ")
    text = metadata["description"].split("\n")

    # filter out empty lines
    res = filter(lambda line: not line.isspace() and line != "", text)
    text = list(res)

    for index, line in enumerate(text):
        # no further process
        # since spaces are automatically ignored in Sphinx
        file.write(f"{line}\n")
        with contextlib.suppress(IndexError):
            if text[index + 1]:
                if is_suite:
                    file.write("                  | ")
                else:
                    file.write("                      | ")
    file.write("\n")
