# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from microsoft.testsuites.kselftest.kselftest import _merge_known_hanging_tests


def test_adds_known_hanging_test_for_affected_kernel() -> None:
    skip_tests, added_tests = _merge_known_hanging_tests("5.4.0-1022-azure-fips", [])

    assert skip_tests == ["ptrace:vmaccess"]
    assert added_tests == ["ptrace:vmaccess"]


def test_preserves_existing_skip_tests_without_duplicates() -> None:
    configured_skip_tests = ["ptrace:vmaccess", "ptrace:set_syscall_info"]

    skip_tests, added_tests = _merge_known_hanging_tests(
        "5.4.0-1022-azure-fips", configured_skip_tests
    )

    assert skip_tests == configured_skip_tests
    assert skip_tests is not configured_skip_tests
    assert added_tests == []


def test_does_not_add_skip_for_other_kernels() -> None:
    for kernel_version in ["5.4.0-1023-azure-fips", "5.4.0-1022-azure"]:
        skip_tests, added_tests = _merge_known_hanging_tests(kernel_version, None)

        assert skip_tests == []
        assert added_tests == []
