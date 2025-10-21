# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import os
import re
from pathlib import Path

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner
from lisa.tools import Gcc, Gdb
from lisa.util import get_matched_str


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers gdb functionality.
    """,
)
class GDB(TestSuite):
    # Hello World![Inferior 1 (process 1869) exited normally]
    _gdb_output_pattern = re.compile(
        r".*Hello World!\[Inferior .* \(process .*\) exited normally\].*"
    )
    _file_name = "hello"
    _test_data_file_path = (
        Path(os.path.dirname(__file__)) / "test_data" / f"{_file_name}.c"
    )

    @TestCaseMetadata(
        description="""
        This test case check gdb work well by checking output.

        1. compile code with gdb options
        2. run gdb with compiled file
        3. expect to see 'Hello World![Inferior 1 (process 1869) exited normally]'
           from output
        """,
        priority=2,
    )
    def verify_gdb(self, node: Node) -> None:
        # copy hello.c into test machine
        to_be_compiled_file_path = node.working_path / f"{self._file_name}.c"
        compiled_file_path = node.working_path / self._file_name
        if not node.shell.exists(node.working_path / self._test_data_file_path):
            node.shell.copy(self._test_data_file_path, to_be_compiled_file_path)

        # compile code with gdb options
        if type(node.os) is CBLMariner:
            node.os.install_packages(("binutils", "glibc-devel"))
        node.tools[Gcc].compile(
            str(to_be_compiled_file_path), str(compiled_file_path), "-g -ggdb"
        )

        # run gdb with compiled file
        output = node.tools[Gdb].debug(
            str(compiled_file_path), "-batch -ex 'run' -ex 'bt'"
        )

        # expect to see 'Hello World![Inferior 1 (process 1869) exited normally]'
        # from output
        matched = get_matched_str(output, self._gdb_output_pattern)
        assert_that(matched).described_as(
            f"dbg result doesn't matched expected value, actual output is {output}"
        ).is_not_empty()
