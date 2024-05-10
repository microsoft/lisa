# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
import os
import subprocess
from typing import Any

LOGFORMAT = "%(asctime)s.%(msecs)03d[%(thread)d][%(levelname)s] %(name)s %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def execute(command: str, is_json: bool = False, check: bool = True) -> Any:
    env = os.environ.copy()
    process_result = subprocess.run(
        command, shell=True, env=env, capture_output=True, text=True, check=False
    )
    if process_result.returncode != 0:
        message = (
            f"failed to execute command: '{command}', error: {process_result.stderr}"
        )
        if check:
            raise SystemExit(message)
        else:
            logging.debug(message)
    if is_json:
        result = _parse_json(process_result.stdout)
    else:
        result = process_result.stdout

    return result


def _parse_json(content: str) -> Any:
    return json.loads(content)
