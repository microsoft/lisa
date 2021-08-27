# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ast
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

TESTS = Path("./test_paths.yaml")
EXTS = Path("./api_paths.yaml")


# TODO - API
class DocGenerator:
    def __init__(self, filename: Path) -> None:
        assert str(filename)[-3:] == ".py"
        self._filename = filename


class ClassVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._class_names: Set[Any] = set()
        self._suites: Set[Any] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa
        """
        Overrides parent method in ast.NodeVisitor, traverses all classes
        """
        decorators = node.decorator_list
        for deco in decorators:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name):
                if deco.func.id == "TestSuiteMetadata":
                    self._suites.add(node)
        if isinstance(node, ast.ClassDef):
            self._class_names.add(node.name)

    def get_suites(self) -> Set[Any]:
        return self._suites

    def get_class_names(self) -> Set[Any]:
        return self._class_names


class FuncVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._cases: Set[Any] = set()
        self._names: Set[Any] = set()
        self._constants: Set[Any] = set()

    def get_cases(self) -> Set[Any]:
        return self._cases

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa
        """
        Overrides parent method in ast.NodeVisitor, traverses all functions
        """
        decorators = node.decorator_list
        for deco in decorators:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name):
                if deco.func.id == "TestCaseMetadata":
                    self._cases.add(node)


def add_req(s: str, req: str) -> str:
    """
    A helper function to format test requirement.

    Args:
        s (str): prefix, particularly, "supported_features"
        req (str): requirement to add

    Returns:
        str: complete formatted requirement
    """
    if "[" not in s:
        s = s + "[" + req + "]"
    else:
        s = s[:-1] + ", " + req + "]"
    return s


def extract_metadata(nodes: Set[Any]) -> List[Dict[str, str]]:
    """
    Main function to extract and format metadata

    Args:
        nodes (Set[Any]): nodes containing metadata

    Returns:
        List[Dict[str, str]]: formatted metadata
    """
    metadata: Dict[str, str] = {}
    all_metadata = []
    for node in nodes:
        metadata["name"] = node.name
        for deco in node.decorator_list:
            for param in deco.keywords:
                field = param.arg

                if isinstance(param.value, ast.Call):  # requirement
                    for req in param.value.keywords:
                        val = req.arg
                        if isinstance(req.value, ast.Attribute):  # may be wrong
                            val = req.value.value.id + "."  # type: ignore
                            val += req.value.attr  # type: ignore
                        elif isinstance(req.value, ast.Constant):
                            val = req.arg + "=" + str(req.value.value)  # type: ignore
                        elif isinstance(req.value, ast.List):
                            for r in req.value.elts:
                                if isinstance(r, ast.Name):
                                    val = add_req(val, r.id)  # type: ignore
                else:
                    val = param.value.value

                metadata[field] = val  # type: ignore
        all_metadata.append(metadata)
        metadata = {}  # re-initialize
    return all_metadata


def load_path(file_path: Path) -> List[Dict[str, str]]:
    """
    load file paths from a user-friendly yaml file

    Args:
        file_path (Path): path to the yaml file

    Returns:
        Dict[str, str]: usually name as key and path as value
    """
    base_path = Path(__file__).parent
    path = (base_path / file_path).resolve()

    with open(path, "r") as file:
        data: List[Dict[str, str]] = yaml.safe_load(file)

    return data
