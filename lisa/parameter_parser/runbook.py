# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, cast

import yaml
from marshmallow import Schema

from lisa import schema
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.package import import_package
from lisa.variable import VariableEntry, load_variables, replace_variables

_schema: Optional[Schema] = None

_get_init_logger = partial(get_logger, "init", "runbook")


class RunbookBuilder:
    def __init__(
        self,
        path: Path,
        cmd_args: Optional[List[str]] = None,
    ) -> None:
        if cmd_args is None:
            cmd_args = []

        self._log = _get_init_logger()
        self._path = path
        self._cmd_args = cmd_args

        self._raw_data: Any = None
        self._variables: Dict[str, VariableEntry] = {}
        constants.RUNBOOK_PATH = self._path.parent
        constants.RUNBOOK_FILE = self._path

    @property
    def variables(self) -> Dict[str, VariableEntry]:
        return self._variables

    @property
    def raw_data(self) -> Any:
        return self._raw_data

    @property
    def runbook(self) -> schema.Runbook:
        return self.resolve()

    @staticmethod
    def from_path(
        path: Path,
        cmd_args: Optional[List[str]] = None,
    ) -> "RunbookBuilder":
        """
        Loads a runbook given a user-supplied path and set of variables.
        """
        builder = RunbookBuilder(path=path, cmd_args=cmd_args)

        # merge all parameters
        builder._log.info(f"loading runbook: {builder._path}")
        data = builder._load_data(
            path=builder._path.absolute(), higher_level_variables=builder._cmd_args
        )
        builder._raw_data = data

        # load final variables
        variables = load_variables(
            runbook_data=data, higher_level_variables=builder._cmd_args
        )
        builder._variables = variables

        builder._import_extensions()

        # remove variables and extensions from data, since it's not used, and may be
        #  confusing in log.
        builder._remove_variables()

        runbook_name = builder.partial_resolve(constants.NAME)

        constants.RUN_NAME = f"lisa-{runbook_name}-{constants.RUN_ID}"
        builder._log.info(f"run name is '{constants.RUN_NAME}'")

        return builder

    def resolve(
        self, variables: Optional[Dict[str, VariableEntry]] = None
    ) -> schema.Runbook:
        parsed_data = self._internal_resolve(self.raw_data, variables)

        # validate runbook, after extensions loaded
        runbook = self._validate_and_load(parsed_data)

        return runbook

    def partial_resolve(
        self, partial_name: str, variables: Optional[Dict[str, VariableEntry]] = None
    ) -> Any:
        result: Any = None
        if partial_name in self.raw_data:
            raw_data = copy.deepcopy(self.raw_data[partial_name])
            result = self._internal_resolve(raw_data, variables)

        return result

    def derive(
        self, variables: Optional[Dict[str, VariableEntry]] = None
    ) -> "RunbookBuilder":
        """
        create a new instance with a copy of variables. If the variables is not
        given, it copies current variables
        """
        result = RunbookBuilder(self._path, self._cmd_args)
        if variables is None:
            variables = {key: value.copy() for key, value in self.variables.items()}
        result._variables = variables
        # merge variables derived from combinators or transformers.
        result._variables.update(variables)
        # reload data to support dynamic path in combinators or transformers.
        result._raw_data = result._load_data(
            path=self._path, higher_level_variables=result._variables
        )
        result._remove_extensions()
        result._remove_variables()

        return result

    def dump_variables(self) -> None:
        variables = self.variables
        # log message for unused variables, it's helpful to see which variable
        # is not used.
        unused_keys = [key for key, value in variables.items() if not value.is_used]
        if unused_keys:
            self._log.debug(f"variables {unused_keys} are not used.")

        # print runbook later, after __post_init__ executed, so secrets are handled.
        for key, value in variables.items():
            self._log.debug(f"variable '{key}': {value.data}")

    def _remove_variables(self) -> None:
        self._raw_data.pop(constants.VARIABLE, None)

    def _remove_extensions(self) -> None:
        self._raw_data.pop(constants.EXTENSION, None)

    def _internal_resolve(
        self, raw_data: Any, variables: Optional[Dict[str, VariableEntry]] = None
    ) -> Any:
        raw_data = copy.deepcopy(raw_data)
        if variables is None:
            variables = self.variables
        try:
            parsed_data = replace_variables(raw_data, variables)
        except Exception as e:
            # log current data for troubleshooting.
            self._log.debug(f"parsed raw data: {raw_data}")
            raise e

        return parsed_data

    def _import_extensions(self) -> None:
        # load extended modules
        if constants.EXTENSION in self._raw_data:
            raw_extensions = self._load_extensions(
                constants.RUNBOOK_PATH, self.raw_data, self.variables
            )
            extensions = schema.Extension.from_raw(raw_extensions)
            for index, extension in enumerate(extensions):
                if not extension.name:
                    extension.name = f"lisa_ext_{index}"
                import_package(Path(extension.path), extension.name)

            self._remove_extensions()

    @staticmethod
    def _validate_and_load(data: Any) -> schema.Runbook:
        global _schema
        if not _schema:
            _schema = schema.Runbook.schema()  # type: ignore

        assert _schema
        runbook = cast(schema.Runbook, _schema.load(data))

        log = _get_init_logger()
        log.debug(f"parsed runbook: {runbook.to_dict()}")  # type: ignore

        return runbook

    def _load_extensions(
        self,
        current_path: Path,
        data: Any,
        variables: Optional[Dict[str, VariableEntry]] = None,
    ) -> List[schema.Extension]:
        results: List[schema.Extension] = []
        if constants.EXTENSION in data:
            raw_extensions: Any = data[constants.EXTENSION]

            # replace variables in extensions names
            if variables:
                raw_extensions = replace_variables(raw_extensions, variables=variables)

            # this is the first place to normalize extensions
            extensions = schema.Extension.from_raw(raw_extensions)

            for extension in extensions:
                assert extension.path, "extension path must be specified"

                # resolving to real path, it needs to compare for merging later.
                if variables:
                    extension.path = replace_variables(
                        extension.path, variables=variables
                    )
                extension.path = str(
                    current_path.joinpath(extension.path).absolute().resolve()
                )
                results.append(extension)

        return results

    def _merge_variables(
        self,
        merged_path: Path,
        data_from_include: Dict[str, Any],
        data_from_current: Dict[str, Any],
    ) -> List[Any]:
        variables_from_include: List[schema.Variable] = []
        if (
            constants.VARIABLE in data_from_include
            and data_from_include[constants.VARIABLE]
        ):
            variables_from_include = [
                schema.load_by_type(schema.Variable, variable)
                for variable in data_from_include[constants.VARIABLE]
            ]
            # resolve to absolute path
            for included_var in variables_from_include:
                if included_var.file:
                    included_var.file = str((merged_path / included_var.file).resolve())
        if (
            constants.VARIABLE in data_from_current
            and data_from_current[constants.VARIABLE]
        ):
            variables_from_current: List[schema.Variable] = [
                schema.load_by_type(schema.Variable, variable)
                for variable in data_from_current[constants.VARIABLE]
            ]

            # remove duplicate items
            for current_variable in variables_from_current:
                for included_var in variables_from_include:
                    if (
                        included_var.name and included_var.name == current_variable.name
                    ) or (
                        included_var.file and included_var.file == current_variable.file
                    ):
                        variables_from_include.remove(included_var)
                        break
            variables_from_include.extend(variables_from_current)

        # serialize back for loading together
        return [
            variable.to_dict() for variable in variables_from_include  # type: ignore
        ]

    def _merge_extensions(
        self,
        merged_path: Path,
        data_from_include: Dict[str, Any],
        data_from_current: Dict[str, Any],
    ) -> List[Any]:
        old_extensions = self._load_extensions(merged_path, data_from_include)
        extensions = self._load_extensions(merged_path, data_from_current)
        # remove duplicate paths
        for old_extension in old_extensions:
            for extension in extensions:
                if extension.path == old_extension.path:
                    if not old_extension.name:
                        # specify name as possible
                        old_extension.name = extension.name
                    extensions.remove(extension)
                    break
        if extensions or old_extensions:
            # don't change the order, old ones should be imported earlier.
            old_extensions.extend(extensions)
            extensions = old_extensions
        return extensions

    def _merge_data(
        self,
        merged_path: Path,
        data_from_include: Dict[str, Any],
        data_from_current: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge included data to data_from_current. The current data has
        higher precedence.
        """
        result = data_from_include.copy()

        # merge others
        result.update(data_from_current)

        # merge variables, latest should be effective last
        variables = self._merge_variables(
            merged_path, data_from_include, data_from_current
        )
        if variables:
            result[constants.VARIABLE] = variables

        # merge extensions
        extensions = self._merge_extensions(
            merged_path, data_from_include, data_from_current
        )
        if extensions:
            result[constants.EXTENSION] = extensions

        return result

    def _load_data(
        self,
        path: Path,
        higher_level_variables: Union[List[str], Dict[str, VariableEntry]],
        used_path: Optional[Set[str]] = None,
    ) -> Any:
        """
        Load runbook, but not to validate. It will be validated after
        extensions are imported. To support partial runbooks, it loads
        recursively.
        """

        with open(path, "r") as file:
            data_from_current = yaml.safe_load(file)
        if not data_from_current:
            raise LisaException(f"file '{path}' cannot be empty.")

        if not used_path:
            used_path = set()

        variables = load_variables(
            data_from_current, higher_level_variables=higher_level_variables
        )

        if (
            constants.INCLUDE in data_from_current
            and data_from_current[constants.INCLUDE]
        ):
            includes = data_from_current[constants.INCLUDE]

            log = _get_init_logger()
            indent = len(used_path) * 4 * " "

            data_from_include: Dict[str, Any] = {}
            for include_raw in includes:
                try:
                    include: schema.Include
                    include = schema.load_by_type(schema.Include, include_raw)
                except Exception as e:
                    raise LisaException(
                        f"error on loading include node [{include_raw}]: {e}"
                    )
                if include.strategy:
                    raise NotImplementedError(
                        "include runbook entry doesn't implement Strategy"
                    )

                raw_path = include.path
                if variables:
                    raw_path = replace_variables(raw_path, variables)
                if raw_path in used_path:
                    raise LisaException(
                        f"circular reference on runbook includes detected: {raw_path}"
                    )

                # use relative path to included runbook
                include_path = (path.parent / raw_path).resolve().absolute()
                log.debug(f"{indent}loading include: {raw_path}")

                # clone a set to support same path is used in different tree.
                new_used_path = used_path.copy()
                new_used_path.add(raw_path)
                include_data = self._load_data(
                    path=include_path,
                    higher_level_variables=variables,
                    used_path=new_used_path,
                )
                data_from_include = self._merge_data(
                    include_path.parent, include_data, data_from_include
                )
            data_from_current = self._merge_data(
                path.parent, data_from_include, data_from_current
            )

        return data_from_current
