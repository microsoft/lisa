# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
This script generates fine-tune data for AI models.
"""
import ast
import json
import os
from pathlib import Path
from typing import Dict

from .doc_generator import TESTS, ClassVisitor, FuncVisitor, extract_metadata, load_path

base_path = Path(__file__).parent
file_path = (base_path / "../_build/html/finetune_cases.jsonl").resolve()
system_prompt = "You are a helpful assistant to write Python code for linux validation."
user_prompt = "Please write LISA test cases based on the test case descriptions.\n\n\n"


def update_finetune_data() -> None:
    """
    Updates (rewrites) fine tune data for AI models.
    """
    data = load_path(TESTS)
    test_paths = [(base_path / Path(x.get("value", ""))).resolve() for x in data]

    file_path_parent = file_path.parent
    if not os.path.exists(file_path_parent):
        os.makedirs(file_path_parent)

    with open(file_path, "w", encoding="utf-8") as f:
        for test_path in test_paths:
            for root, _, files in os.walk(test_path):
                for file in files:
                    if file.endswith(".py"):
                        descriptions = "test suite description:\n"
                        test_name = Path(root) / file
                        tree = ast.parse(
                            test_name.read_text(encoding="utf-8"),
                            filename=str(test_name),
                        )
                        cls_visitor = ClassVisitor()
                        func_visitor = FuncVisitor()
                        cls_visitor.visit(tree)
                        func_visitor.visit(tree)

                        for suite_metadata in extract_metadata(
                            cls_visitor.get_suites()
                        ):
                            descriptions += _get_description(suite_metadata, True)
                            descriptions += "\n\n"
                            for case in extract_metadata(func_visitor.get_cases()):
                                descriptions += "test case:\n"
                                descriptions += _get_description(case)
                                descriptions += "\n\n"

                        source = test_name.read_text(encoding="utf-8")

                        f.write(
                            json.dumps(
                                {
                                    "messages": [
                                        {"role": "system", "content": system_prompt},
                                        {
                                            "role": "user",
                                            "content": user_prompt + descriptions,
                                        },
                                        {"role": "assistant", "content": source},
                                    ]
                                }
                            )
                            + "\n"
                        )


def _get_description(metadata: Dict[str, str], is_suite: bool = False) -> str:
    text = metadata["description"].split("\n")

    # filter out empty lines
    res = filter(lambda line: not line.isspace() and line != "", text)
    text = list(res)

    return "\n".join(text)
