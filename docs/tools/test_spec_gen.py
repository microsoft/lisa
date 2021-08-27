# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Update test_spec.rst with test metadata
"""

import ast
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

    with open(file_path, "w") as test_spec:
        _write_title(test_spec)

        for test_path in test_paths:
            for root, _, files in os.walk(test_path):
                for file in files:
                    if file.endswith(".py"):
                        # print("Processing " + file)
                        test_name = Path(root) / file
                        with open(test_name, "r") as f:
                            contents = f.read()
                            tree = ast.parse(contents)
                        cls_visitor = ClassVisitor()
                        func_visitor = FuncVisitor()
                        cls_visitor.visit(tree)
                        func_visitor.visit(tree)

                        for suite in extract_metadata(cls_visitor.get_suites()):
                            _write_suite(test_spec, suite)
                            for case in extract_metadata(func_visitor.get_cases()):
                                _write_case(test_spec, case)


def _write_title(file: TextIO) -> None:
    """
    Writes the title of test specifications

    Args:
        file (TextIO): test spec file
    """
    title = "Test Specification"
    file.write(title + "\n")
    file.write("=" * len(title) + "\n")
    file.write("\n")

    file.write("This file lists all test cases' specifications.\n")
    file.write("\n")


def _write_suite(file: TextIO, metadata: Dict[str, str]) -> None:
    """
    Writes info of a test suite.

    Args:
        file (TextIO): test spec file
        metadata (Dict[str, str]): test suite metadata
    """
    file.write(".. _" + metadata["name"] + ":\n")  # custom anchor
    file.write("\n")

    file.write(".. class:: ")
    file.write(metadata["name"] + "\n")  # Test Suite Name
    file.write("    :noindex:" + "\n")
    file.write("\n")

    _write_description(file, metadata, True)  # Description

    file.write("    :platform: ")
    file.write("``" + "Azure, Ready" + "``\n")  # Platform

    file.write("    :area: ")
    file.write("``" + metadata["area"] + "``\n")  # Area

    file.write("    :category: ")
    file.write("``" + metadata["category"] + "``\n")  # Category
    file.write("\n")


def _write_case(file: TextIO, metadata: Dict[str, str]) -> None:
    """
    Writes info of a test case.

    Args:
        file (TextIO): test spec file
        metadata (Dict[str, str]): test case metadata
    """
    file.write(".. _" + metadata["name"] + ":\n")  # custom anchor
    file.write("\n")

    file.write("    .. method:: ")
    file.write(metadata["name"] + "\n")  # Test Case Name
    file.write("        :noindex:" + "\n")
    file.write("\n")

    file.write("    ")  # 1-tab indentation
    _write_description(file, metadata)  # Description

    file.write("        :priority: ")
    file.write("``" + str(metadata["priority"]) + "``\n")  # Priority

    if "requirement" in metadata.keys():
        file.write("        :requirement: ")
        file.write("``" + str(metadata["requirement"]) + "``\n")  # Requirement

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
    res = filter(lambda line: (not line.isspace()) and (not line == ""), text)
    text = list(res)

    index = -1
    for line in text:
        index += 1
        # no further process
        # since spaces are automatically ignored in Sphinx
        file.write(line)
        file.write("\n")
        try:
            if text[index + 1]:  # if end of list
                if is_suite:
                    file.write("                  | ")
                else:
                    file.write("                      | ")
        except IndexError:
            pass
    file.write("\n")
