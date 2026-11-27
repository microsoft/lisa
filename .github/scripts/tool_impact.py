# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Trace in-file Tool implementations, consumers and guarded call sites."""

import ast
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Set, Tuple


@dataclass
class ToolImpact:
    tools: Set[str] = field(default_factory=set)
    factory_guards: List[ast.expr] = field(default_factory=list)
    guarded_calls: List[Tuple[str, ast.expr, str]] = field(default_factory=list)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _retrieved_tool(node: ast.AST) -> str:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "tools"
    ):
        return _name(node.slice)
    return ""


def _guards(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> Iterator[ast.expr]:
    while node in parents:
        parent = parents[node]
        if isinstance(parent, ast.If):
            if node in parent.body:
                yield parent.test
            elif node is not parent.test and (
                parent.orelse != [node] or not isinstance(node, ast.If)
            ):
                yield ast.UnaryOp(op=ast.Not(), operand=parent.test)
        node = parent


def _implementation_guards(
    classes: Dict[str, ast.ClassDef],
    changed: Set[str],
    parents: Dict[ast.AST, ast.AST],
) -> List[ast.expr]:
    guards: List[ast.expr] = []
    for owner in classes.values():
        for method in owner.body:
            if not isinstance(method, ast.FunctionDef) or method.name != "create":
                continue
            for node in ast.walk(method):
                value = (
                    node.value
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return))
                    else None
                )
                if value is not None and (
                    _name(value) in changed
                    or isinstance(value, ast.Call)
                    and _name(value.func) in changed
                ):
                    guards.extend(_guards(node, parents))
    return guards


def _guarded_calls(
    owner: ast.ClassDef,
    methods: Dict[str, Set[str]],
    parents: Dict[ast.AST, ast.AST],
) -> List[Tuple[str, ast.expr, str]]:
    result: List[Tuple[str, ast.expr, str]] = []
    helpers = {
        node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)
    }
    for method in helpers.values():
        aliases: Dict[str, str] = {}
        for node in ast.walk(method):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            tool = _retrieved_tool(node.value) if node.value is not None else ""
            if tool:
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                aliases.update({ast.unparse(target): tool for target in targets})
        for node in ast.walk(method):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            receiver = node.func.value
            tool = (
                owner.name
                if isinstance(receiver, ast.Name) and receiver.id == "self"
                else _retrieved_tool(receiver) or aliases.get(ast.unparse(receiver), "")
            )
            if tool not in methods.get(node.func.attr, set()):
                continue
            for guard in _guards(node, parents):
                helper_source = "\n".join(
                    ast.unparse(helpers[call.func.attr])
                    for call in ast.walk(guard)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "self"
                    and call.func.attr in helpers
                )
                result.append((f"{owner.name}.{method.name}", guard, helper_source))
    return result


def tool_change_impact(source: ast.Module, lines: Set[int]) -> ToolImpact:
    classes = {
        node.name: node for node in source.body if isinstance(node, ast.ClassDef)
    }
    bases = {
        name: {_name(base) for base in owner.bases} for name, owner in classes.items()
    }
    tool_classes = {"Tool"}
    while True:
        derived = {name for name in classes if bases[name] & tool_classes}
        if derived <= tool_classes:
            break
        tool_classes.update(derived)
    changed = {
        name
        for name, owner in classes.items()
        if name in tool_classes
        and any(
            owner.lineno <= line <= (owner.end_lineno or owner.lineno) for line in lines
        )
    }
    if not changed:
        return ToolImpact()

    impacted = set(changed)
    while True:
        ancestors = set().union(*(bases.get(name, set()) for name in impacted))
        consumers = {
            name
            for name, owner in classes.items()
            if name in tool_classes
            and any(_retrieved_tool(node) in impacted for node in ast.walk(owner))
        }
        added = (ancestors | consumers) & classes.keys()
        if added <= impacted:
            break
        impacted.update(added)

    parents = {
        child: node for node in ast.walk(source) for child in ast.iter_child_nodes(node)
    }
    methods: Dict[str, Set[str]] = {}
    for name in changed:
        ancestors = {name}
        while True:
            added = set().union(*(bases.get(item, set()) for item in ancestors))
            if added <= ancestors:
                break
            ancestors.update(added)
        for method in classes[name].body:
            if isinstance(method, ast.FunctionDef) and any(
                method.lineno <= line <= (method.end_lineno or method.lineno)
                for line in lines
            ):
                methods.setdefault(method.name, set()).update(ancestors)

    return ToolImpact(
        tools=impacted,
        factory_guards=_implementation_guards(classes, changed, parents),
        guarded_calls=[
            call
            for name, owner in classes.items()
            if name in tool_classes
            for call in _guarded_calls(owner, methods, parents)
        ],
    )
