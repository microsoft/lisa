# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import functools
from typing import Any, Dict, List, Optional, Set

from lisa import schema
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.util import InitializableMixin, LisaException, constants, subclasses
from lisa.util.logger import get_logger
from lisa.variable import VariableEntry, merge_variables

_get_init_logger = functools.partial(get_logger, "init", "transformer")


class Transformer(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self,
        runbook: schema.Transformer,
        runbook_builder: RunbookBuilder,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self.name = runbook.name
        self.prefix = runbook.prefix
        self.depends_on = runbook.depends_on
        self.rename = runbook.rename

        self._runbook_builder = runbook_builder
        self._log = get_logger("transformer", self.name)

    def run(self) -> Dict[str, VariableEntry]:
        """
        Call by the transformer flow, don't override it in subclasses.
        """

        self._log.info("transformer is running.")
        variables = self._internal_run()

        results: Dict[str, VariableEntry] = dict()
        unmatched_rename = copy.copy(self.rename)
        for name, value in variables.items():
            name = f"{self.prefix}_{name}"
            if name in self.rename:
                del unmatched_rename[name]
                name = self.rename[name]
            results[name] = VariableEntry(name, value)
        self._log.debug(f"returned variables: {[x for x in results]}")
        if unmatched_rename:
            raise LisaException(f"unmatched rename variable: {unmatched_rename}")
        return results

    @property
    def _output_names(self) -> List[str]:
        """
        List names of outputs, which are returned after run. It uses for
        pre-validation before the real run. It helps identifying variable name
        errors early.
        """
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        ...

    def _internal_run(self) -> Dict[str, Any]:
        """
        The logic to transform
        """
        raise NotImplementedError()


def _sort(transformers: List[schema.Transformer]) -> List[schema.Transformer]:
    visited: Set[str] = set()
    transformers_by_name: Dict[str, schema.Transformer] = {}
    sorted_transformers: List[schema.Transformer] = []

    # construct full set and check duplicates
    for transformer in transformers:
        if transformer.name in transformers_by_name:
            raise LisaException(
                f"found duplicate transformers: '{transformer.name}', "
                f"use different names for them."
            )
        transformers_by_name[transformer.name] = transformer

    # build new sorted results
    for transformer in transformers:
        if transformer.name not in visited:
            _sort_dfs(transformers_by_name, transformer, visited, sorted_transformers)

    # sort by phase: init, expanded.
    init_transformers: List[schema.Transformer] = []
    expanded_transformers: List[schema.Transformer] = []
    expanded_cleanup_transformers: List[schema.Transformer] = []
    cleanup_transformers: List[schema.Transformer] = []
    for transformer in sorted_transformers:
        if transformer.phase == constants.TRANSFORMER_PHASE_INIT:
            init_transformers.append(transformer)
        elif transformer.phase == constants.TRANSFORMER_PHASE_EXPANDED:
            expanded_transformers.append(transformer)
        elif transformer.phase == constants.TRANSFORMER_PHASE_EXPANDED_CLEANUP:
            expanded_cleanup_transformers.append(transformer)
        elif transformer.phase == constants.TRANSFORMER_PHASE_CLEANUP:
            cleanup_transformers.append(transformer)
        else:
            raise LisaException(f"unknown transformer phase: {transformer.phase}")
    sorted_transformers = (
        init_transformers
        + expanded_transformers
        + expanded_cleanup_transformers
        + cleanup_transformers
    )

    # check cycle reference
    referenced: Set[str] = set()
    for transformer in sorted_transformers:
        for item in transformer.depends_on:
            if item not in referenced:
                raise LisaException(
                    f"found cycle dependent transformers: "
                    f"'{transformer.name}' and '{item}'"
                )
        referenced.add(transformer.name)

    return sorted_transformers


def _sort_dfs(
    transformers: Dict[str, schema.Transformer],
    transformer: schema.Transformer,
    visited: Set[str],
    sorted_transformers: List[schema.Transformer],
) -> None:
    visited.add(transformer.name)
    for item in transformer.depends_on:
        if item not in visited:
            dependent = transformers.get(item, None)
            if not dependent:
                raise LisaException(
                    f"transformer '{transformer.name}' "
                    f"depends on non-existing transformer "
                    f"'{item}'"
                )
            _sort_dfs(transformers, dependent, visited, sorted_transformers)
    sorted_transformers.append(transformer)


def _load_transformers(
    runbook_builder: RunbookBuilder,
    variables: Optional[Dict[str, VariableEntry]] = None,
) -> Dict[str, schema.Transformer]:
    transformers_data = runbook_builder.partial_resolve(
        partial_name=constants.TRANSFORMER, variables=variables
    )
    transformers = schema.load_by_type_many(schema.Transformer, transformers_data)

    return {x.name: x for x in transformers}


def _run_transformers(
    runbook_builder: RunbookBuilder,
    phase: str = constants.TRANSFORMER_PHASE_INIT,
) -> Dict[str, VariableEntry]:
    # resolve variables
    transformers_dict = _load_transformers(runbook_builder=runbook_builder)

    transformers_runbook = [x for x in transformers_dict.values()]
    # resort the runbooks, and it's used in real run
    transformers_runbook = _sort(transformers_runbook)

    copied_variables: Dict[str, VariableEntry] = dict()
    for value in runbook_builder.variables.values():
        copied_variables[value.name] = value.copy()

    factory = subclasses.Factory[Transformer](Transformer)
    for runbook in transformers_runbook:
        # load the original runbook to solve variables again.
        raw_transformers = _load_transformers(
            runbook_builder=runbook_builder, variables=copied_variables
        )
        runbook = raw_transformers[runbook.name]

        # if phase is empty, pick up all of them.
        if not runbook.enabled or (phase and runbook.phase != phase):
            continue

        derived_builder = runbook_builder.derive(copied_variables)
        transformer = factory.create_by_runbook(
            runbook=runbook, runbook_builder=derived_builder
        )
        transformer.initialize()
        values = transformer.run()
        merge_variables(copied_variables, values)

    return copied_variables


def run(
    runbook_builder: RunbookBuilder, phase: str = constants.TRANSFORMER_PHASE_INIT
) -> None:
    log = _get_init_logger()

    root_runbook_data = runbook_builder.raw_data
    if constants.TRANSFORMER not in root_runbook_data:
        log.debug("no transformer found, skipped")
        return

    # real run
    log.debug(f"detecting or running transformers of phase '{phase}'...")
    output_variables = _run_transformers(runbook_builder, phase=phase)
    merge_variables(runbook_builder.variables, output_variables)
