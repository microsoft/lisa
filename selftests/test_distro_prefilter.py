# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List
from unittest import TestCase

from lisa.operating_system import (
    BSD,
    SLES,
    AlmaLinux,
    CBLMariner,
    CentOs,
    CoreOs,
    Debian,
    Fedora,
    FreeBSD,
    Linux,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.util.os_resolver import (
    _infer_from_image_string,
    infer_target_os,
    resolve_os_class,
)

# A standalone TestSuiteMetadata used as the .suite reference on every mock
# case. We construct it directly (without invoking it as a decorator) so the
# global suite/case registry stays untouched and tests do not leak metadata
# to each other.
_MOCK_SUITE = TestSuiteMetadata(
    area="a_prefilter",
    category="c_prefilter",
    description="prefilter mock suite",
    tags=[],
    name="PrefilterMock",
)


def _build_case(
    name: str,
    *,
    supported_os: Any = None,
    unsupported_os: Any = None,
) -> TestCaseMetadata:
    """Construct a TestCaseMetadata with the requested OS requirement,
    bypassing the global registry. The returned object can be passed to
    ``select_testcases(init_cases=[...])`` directly.
    """
    requirement = simple_requirement(
        supported_os=supported_os, unsupported_os=unsupported_os
    )
    metadata = TestCaseMetadata(
        description=f"des_{name}", priority=2, requirement=requirement
    )
    # Mimic the attributes that __call__ would set if this were used as a
    # real decorator. select_testcases keys cases by full_name and logs via
    # metadata.suite.area / .category, so both are required.
    metadata.name = name
    metadata.full_name = f"{_MOCK_SUITE.name}.{name}"
    metadata.suite = _MOCK_SUITE
    metadata.tags = []
    return metadata


class ResolveOsClassTestCase(TestCase):
    def test_resolve_known_aliases(self) -> None:
        cases = {
            # Debian family (distro + publisher)
            "ubuntu": Ubuntu,
            "Ubuntu": Ubuntu,
            "canonical": Ubuntu,
            "Canonical": Ubuntu,
            "debian": Debian,
            "Debian": Debian,
            # Red Hat family (distro + publisher)
            "rhel": Redhat,
            "redhat": Redhat,
            "RedHat": Redhat,
            "centos": CentOs,
            "CentOS": CentOs,
            "openlogic": CentOs,
            "OpenLogic": CentOs,
            "oracle": Oracle,
            "ol": Oracle,
            "almalinux": AlmaLinux,
            "alma": AlmaLinux,
            # SUSE family
            "suse": Suse,
            "SUSE": Suse,
            "sles": SLES,
            "opensuse": Suse,
            # Fedora
            "fedora": Fedora,
            # Azure Linux / CBL-Mariner (distro + publisher)
            "azurelinux": CBLMariner,
            "azl": CBLMariner,
            "mariner": CBLMariner,
            "cbl-mariner": CBLMariner,
            "CBL_Mariner": CBLMariner,
            "cblmariner": CBLMariner,
            "microsoftcblmariner": CBLMariner,
            "MicrosoftCBLMariner": CBLMariner,
            # BSD family (distro + publisher)
            "freebsd": FreeBSD,
            "FreeBSD": FreeBSD,
            "microsoftcbsd": FreeBSD,
            "bsd": BSD,
            # Other
            "coreos": CoreOs,
            "flatcar": CoreOs,
            "kinvolk": CoreOs,
            "linux": Linux,
            "windows": Windows,
        }
        for name, expected in cases.items():
            self.assertIs(resolve_os_class(name), expected, msg=f"name={name}")

    def test_resolve_class_name_directly(self) -> None:
        self.assertIs(resolve_os_class("Debian"), Debian)
        self.assertIs(resolve_os_class("Linux"), Linux)

    def test_resolve_unknown_returns_none(self) -> None:
        self.assertIsNone(resolve_os_class("notadistro"))
        self.assertIsNone(resolve_os_class(""))
        self.assertIsNone(resolve_os_class(None))


class InferFromImageTestCase(TestCase):
    def test_infer_marketplace_strings(self) -> None:
        cases = {
            # Ubuntu
            "Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest": Ubuntu,
            "canonical 0001-com-ubuntu-server-focal 20_04-lts-gen2 latest": Ubuntu,
            "canonical ubuntuserver 18.04-lts latest": Ubuntu,
            # Debian
            "Debian debian-12 12 latest": Debian,
            "debian debian-11 11-gen2 latest": Debian,
            # Red Hat
            "RedHat RHEL 9-lvm-gen2 latest": Redhat,
            "redhat rhel 8-lbr-gen2 latest": Redhat,
            "redhat rhel-byos 8_4 latest": Redhat,
            # CentOS
            "OpenLogic CentOS 7_9-gen2 latest": CentOs,
            "openlogic centos-hpc 7.6 latest": CentOs,
            # Oracle
            "Oracle Oracle-Linux ol79-gen2 latest": Oracle,
            "oracle oracle-linux ol88-lvm-gen2 latest": Oracle,
            # AlmaLinux
            "almalinux almalinux 8-gen2 latest": AlmaLinux,
            "almalinux almalinux-x86_64 9-gen2 latest": AlmaLinux,
            # SUSE / SLES (publisher 'suse' matches the Suse alias)
            "SUSE sles-15-sp5 gen2 latest": Suse,
            "suse sles-byos 12-sp5-gen2 latest": Suse,
            "suse opensuse-leap-15-5 gen2 latest": Suse,
            # Fedora
            "fedora fedora-coreos stable latest": Fedora,
            # CBL-Mariner / Azure Linux
            "MicrosoftCBLMariner cbl-mariner 2-gen2 latest": CBLMariner,
            "microsoftcblmariner cbl-mariner cbl-mariner-2 gen2": CBLMariner,
            "microsoftcblmariner azurelinux-3 3-gen2 latest": CBLMariner,
            # FreeBSD
            "MicrosoftCBSD FreeBSD 13.2 latest": FreeBSD,
            # CoreOS / Flatcar
            "kinvolk flatcar-container-linux-free stable-gen2 latest": CoreOs,
        }
        for image, expected in cases.items():
            self.assertIs(
                _infer_from_image_string(image), expected, msg=f"image={image}"
            )

    def test_infer_returns_none_for_opaque_strings(self) -> None:
        self.assertIsNone(_infer_from_image_string(""))
        self.assertIsNone(_infer_from_image_string("private-image-v1"))

    def test_infer_vhd_strings(self) -> None:
        cases = {
            "https://storage.blob.core.windows.net/vhds/ubuntu-22.04.vhd": Ubuntu,
            "https://storage.blob.core.windows.net/vhds/rhel-9.2-gen2.vhd": Redhat,
            "/subscriptions/.../images/azurelinux-3.0.vhd": CBLMariner,
            "https://sa.blob.core.windows.net/images/debian-12.vhd": Debian,
            "/path/to/sles-15-sp5.vhd": SLES,
            "https://sa.blob.core.windows.net/vhds/custom-image-v1.vhd": None,
        }
        for vhd, expected in cases.items():
            result = _infer_from_image_string(vhd)
            self.assertIs(
                result, expected, msg=f"vhd={vhd}, got={result}, expected={expected}"
            )

    def test_infer_shared_gallery_strings(self) -> None:
        cases = {
            "/galleries/myGallery/images/ubuntu-22.04-gen2/versions/1.0.0": Ubuntu,
            "/galleries/myGallery/images/mariner-2-gen2/versions/latest": CBLMariner,
            "/galleries/testGallery/images/rhel-9-lvm/versions/2.0.0": Redhat,
        }
        for gallery, expected in cases.items():
            result = _infer_from_image_string(gallery)
            self.assertIs(result, expected, msg=f"gallery={gallery}")


class InferTargetOsTestCase(TestCase):
    def test_infers_from_marketplace_image(self) -> None:
        variables: Dict[str, Any] = {
            "marketplace_image": (
                "Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest"
            ),
        }
        self.assertIs(infer_target_os(variables), Ubuntu)

    def test_returns_none_when_no_hints(self) -> None:
        self.assertIsNone(infer_target_os(None))
        self.assertIsNone(infer_target_os({}))
        self.assertIsNone(infer_target_os({"some_unrelated_var": "value"}))

    def test_returns_none_for_opaque_image(self) -> None:
        variables: Dict[str, Any] = {
            "marketplace_image": "private-image-v1",
        }
        self.assertIsNone(infer_target_os(variables))

    def test_unwraps_variable_entry_objects(self) -> None:
        # Runners pass ``Dict[str, VariableEntry]``; the resolver must read
        # the wrapped ``data`` attribute, not the entry object itself.
        from lisa.variable import VariableEntry

        variables: Dict[str, Any] = {
            "marketplace_image": VariableEntry(
                name="marketplace_image",
                data="RedHat RHEL 9_4 latest",
            ),
        }
        self.assertIs(infer_target_os(variables), Redhat)

        variables = {
            "marketplace_image": VariableEntry(
                name="marketplace_image",
                data="Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest",
            ),
        }
        self.assertIs(infer_target_os(variables), Ubuntu)


class IsOsCompatibleTestCase(TestCase):
    def test_no_requirement_keeps_case(self) -> None:
        case = _build_case("any_distro")
        self.assertTrue(_is_os_compatible(case, Ubuntu))
        self.assertTrue(_is_os_compatible(case, CBLMariner))
        # Default unsupported_os=[Windows] is injected when both are None.
        self.assertFalse(_is_os_compatible(case, Windows))

    def test_specific_supported_os_keeps_only_matching_target(self) -> None:
        case = _build_case("mariner_only", supported_os=[CBLMariner])
        self.assertTrue(_is_os_compatible(case, CBLMariner))
        self.assertFalse(_is_os_compatible(case, Ubuntu))
        self.assertFalse(_is_os_compatible(case, Redhat))

    def test_broad_supported_os_keeps_specific_target(self) -> None:
        case = _build_case("any_linux", supported_os=[Linux])
        self.assertTrue(_is_os_compatible(case, Ubuntu))
        self.assertTrue(_is_os_compatible(case, CBLMariner))

    def test_specific_supported_os_keeps_broad_target(self) -> None:
        case = _build_case("mariner_only", supported_os=[CBLMariner])
        self.assertTrue(_is_os_compatible(case, Linux))

    def test_unsupported_os_drops_target(self) -> None:
        case = _build_case("not_ubuntu", unsupported_os=[Ubuntu])
        self.assertFalse(_is_os_compatible(case, Ubuntu))
        self.assertTrue(_is_os_compatible(case, CBLMariner))

    def test_unsupported_family_drops_descendants(self) -> None:
        case = _build_case("not_debian", unsupported_os=[Debian])
        self.assertFalse(_is_os_compatible(case, Ubuntu))
        self.assertTrue(_is_os_compatible(case, CBLMariner))


class SelectTestcasesPrefilterTestCase(TestCase):
    def _generate_mixed_cases(self) -> List[TestCaseMetadata]:
        return [
            _build_case("any_linux"),
            _build_case("ubuntu_only", supported_os=[Ubuntu]),
            _build_case("mariner_only", supported_os=[CBLMariner]),
            _build_case("not_ubuntu", unsupported_os=[Ubuntu]),
        ]

    def test_no_target_os_keeps_all_cases(self) -> None:
        cases = self._generate_mixed_cases()
        results = select_testcases(filters=None, init_cases=cases, target_os=None)
        names = sorted(r.name for r in results)
        self.assertEqual(
            names, ["any_linux", "mariner_only", "not_ubuntu", "ubuntu_only"]
        )

    def test_target_ubuntu_drops_mariner_and_not_ubuntu(self) -> None:
        cases = self._generate_mixed_cases()
        results = select_testcases(filters=None, init_cases=cases, target_os=Ubuntu)
        names = sorted(r.name for r in results)
        self.assertEqual(names, ["any_linux", "ubuntu_only"])

    def test_target_mariner_keeps_mariner_and_unrelated(self) -> None:
        cases = self._generate_mixed_cases()
        results = select_testcases(filters=None, init_cases=cases, target_os=CBLMariner)
        names = sorted(r.name for r in results)
        self.assertEqual(names, ["any_linux", "mariner_only", "not_ubuntu"])


class GlobalRegistryPrefilterTestCase(TestCase):
    """Integration test that exercises the same code path the runner uses,
    via the global suite/case registry. Mirrors the existing pattern in
    selftests/test_testselector.py (cleanup_cases_metadata in setUp +
    generate_cases_metadata to register mock suites through the decorator
    path).
    """

    def setUp(self) -> None:
        # Avoid late import cycles by importing the existing fixture only
        # when this test runs.
        from selftests.test_testsuite import cleanup_cases_metadata

        cleanup_cases_metadata()

    def tearDown(self) -> None:
        from selftests.test_testsuite import cleanup_cases_metadata

        cleanup_cases_metadata()

    def test_target_os_drops_from_global_registry(self) -> None:
        from selftests.test_testsuite import generate_cases_metadata

        # Register the standard mock suites in the global registry. None of
        # these mock cases declare a supported_os, so only the default
        # ``unsupported_os=[Windows]`` applies. A Windows target must drop
        # them all; an Ubuntu target must keep them all.
        generate_cases_metadata()

        ubuntu_results = select_testcases(filters=None, target_os=Ubuntu)
        windows_results = select_testcases(filters=None, target_os=Windows)

        self.assertGreater(
            len(ubuntu_results),
            0,
            "Ubuntu target should keep mock cases that have no OS restriction",
        )
        self.assertEqual(
            len(windows_results),
            0,
            "Windows target should drop mock cases (default unsupported_os=[Windows])",
        )
