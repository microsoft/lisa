import logging
from pathlib import Path
from typing import Any, Dict, cast

import yaml
from cerberus import Validator  # type: ignore

from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger


def validate_config(data: Any) -> None:
    v = Validator(_load_schema())
    is_success = v.validate(data)
    if not is_success:
        log = get_logger("init", "schema")
        log.lines(level=logging.ERROR, content=v.errors)
        raise LisaException("met validation errors, see error log for details")


def _load_schema() -> Dict[str, object]:
    schema_path = Path(__file__).parent.joinpath("schema.yml")
    with open(schema_path, "r") as f:
        schema = cast(Dict[str, object], yaml.safe_load(f))
    return schema
