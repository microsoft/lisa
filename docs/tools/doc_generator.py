# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ast
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

tests = Path("./test_paths.yaml")


# TODO - API
class DocGenerator:
    def __init__(self, filename: Path) -> None:
        assert str(filename)[-3:] == ".py"
        self._filename = filename


class ClassVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.classes: Set[Any] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa
        decorators = node.decorator_list
        assert decorators is not None
        for deco in decorators:
            if deco.func.id == "TestSuiteMetadata":  # type: ignore
                self.classes.add(node)

    # TODO - API
    def extract_fields(self) -> Dict[str, str]:
        pass


class FuncVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: Set[Any] = set()
        self.names: Set[Any] = set()
        self.constants: Set[Any] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa
        decorators = node.decorator_list
        assert decorators is not None
        for deco in decorators:
            if deco.func.id == "TestCaseMetadata":  # type: ignore
                self.functions.add(node)


# TODO - API
class ConstVisitor(ast.NodeVisitor):
    def visit_Name(self, node: ast.Name) -> Any:  # noqa
        print("Name:", node.id)

    def visit_Constant(self, node: ast.Constant) -> Any:  # noqa
        print("Const:", node.value)


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
                        else:
                            for r in req.value.elts:  # type: ignore
                                if isinstance(r, ast.Name):
                                    val = add_req(val, r.id)  # type: ignore
                else:
                    val = param.value.value

                metadata[field] = val  # type: ignore
        all_metadata.append(metadata)
        metadata = {}  # re-initialize
    return all_metadata


def load_test_path(test_path: Path = tests) -> Dict[str, str]:
    base_path = Path(__file__).parent
    path = (base_path / test_path).resolve()

    with open(path, "r") as file:
        data: Dict[str, str] = yaml.safe_load(file)

    return data
