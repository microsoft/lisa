from unittest import TestCase

from assertpy import assert_that

from lisa.operating_system import CBLMariner


class OperatingSystemTestCase(TestCase):
    def test_get_kernel_version_candidates_for_standard_kernel(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates(
            "kernel-6.6.135-1.azl3.x86_64"
        )

        assert_that(candidates).is_equal_to(["6.6.135-1.azl3"])

    def test_get_kernel_version_candidates_for_flavored_kernel(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates(
            "kernel-lvbs-6.6.135-1.azl3.x86_64"
        )

        assert_that(candidates).is_equal_to(["6.6.135-1.azl3", "6.6.135-lvbs-1.azl3"])

    def test_get_kernel_version_candidates_for_unrecognized_name(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates("custom-kernel")

        assert_that(candidates).is_equal_to(["custom-kernel"])
