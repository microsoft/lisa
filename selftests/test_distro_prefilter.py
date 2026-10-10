# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from argparse import Namespace
from typing import Any, Dict, List
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import OsRequirement, commands, schema
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
from lisa.runners.lisa_runner import LisaRunner
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.testselector import (
    _is_os_compatible,
    _is_platform_compatible,
    select_testcases,
)
from lisa.testsuite import (
    TestCaseMetadata,
    TestSuiteMetadata,
    node_requirement,
    simple_requirement,
)
from lisa.util import LisaException, parse_version
from lisa.util.os_resolver import (
    _infer_from_image_string,
    infer_target_os,
    infer_target_os_info,
    resolve_os_class,
    resolve_target_os,
)
from lisa.variable import VariableEntry

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
    supported_platform_type: Any = None,
    unsupported_platform_type: Any = None,
) -> TestCaseMetadata:
    """Construct a TestCaseMetadata with the requested OS requirement,
    bypassing the global registry. The returned object can be passed to
    ``select_testcases(init_cases=[...])`` directly.
    """
    requirement = simple_requirement(
        supported_os=supported_os,
        unsupported_os=unsupported_os,
        supported_platform_type=supported_platform_type,
        unsupported_platform_type=unsupported_platform_type,
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


class UbuntuVersionPrefilterTestCase(TestCase):
    def test_all_reference_images(self) -> None:
        images = {
            "16.04": [
                "Canonical UbuntuServer 16.04-LTS latest",
                "Canonical UbuntuServer 16_04-lts-gen2 latest",
            ],
            "18.04": [
                "Canonical 0001-com-ubuntu-pro-microsoft 18_04-lts-gen1 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-18_04 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-18_04-gen2 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft 18_04-lts latest",
                "Canonical 0001-com-ubuntu-pro-microsoft 18_04-lts-arm64 latest",
            ],
            "20.04": [
                "canonical 0001-com-ubuntu-server-focal 20_04-lts latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-20_04 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-20_04-gen2 latest",
                "canonical 0001-com-ubuntu-server-focal 20_04-lts-gen2 latest",
                "Canonical 0001-com-ubuntu-confidential-vm-focal 20_04-lts-cvm latest",
                "Canonical 0001-com-ubuntu-server-focal 20_04-lts-arm64 latest",
            ],
            "22.04": [
                "Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest",
                "Canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest",
                "Canonical 0001-com-ubuntu-confidential-vm-jammy 22_04-lts-cvm latest",
                "canonical 0001-com-ubuntu-confidential-vm-jammy "
                "22_04-lts-cvm 22.04.202307140",
                "canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest",
                "canonical 0001-com-ubuntu-pro-microsoft pro-fips-22_04-arm64 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-22_04-gen1 latest",
                "Canonical 0001-com-ubuntu-pro-microsoft pro-fips-22_04 latest",
            ],
            "24.04": [
                "Canonical ubuntu-24_04-lts server-gen1 latest",
                "Canonical ubuntu-24_04-lts server latest",
                "Canonical ubuntu-24_04-lts server-arm64 latest",
                "canonical ubuntu-24_04-lts cvm latest",
                "Canonical ubuntu-24_04-lts cvm 24.04.202407011",
            ],
            "25.10": [
                "Canonical ubuntu-25_10 server-gen1 latest",
                "Canonical ubuntu-25_10 server latest",
                "Canonical ubuntu-25_10 server-arm64 latest",
            ],
            "26.04": [
                "Canonical ubuntu-26_04-lts server-gen1 latest",
                "Canonical ubuntu-26_04-lts server latest",
                "Canonical ubuntu-26_04-lts server-arm64 latest",
                "Canonical ubuntu-26_04-lts server-cvm 26.04.202609020",
                "canonical ubuntu-26_04-lts server-cvm latest",
            ],
        }
        self.assertEqual(34, sum(len(group) for group in images.values()))
        for release, group in images.items():
            for image in group:
                with self.subTest(image=image):
                    target = infer_target_os_info({"marketplace_image": image})
                    assert target
                    self.assertIs(target.os_type, Ubuntu)
                    self.assertEqual(parse_version(release), target.version)

    def test_gallery_and_vhd_release(self) -> None:
        images = [
            "Canonical ubuntu-22_04-lts cvm 24.04.202407011",
            "subscription/group/gallery/"
            "ubuntu_jammy_linux-azure_6.8.0-1071.79.22.04.1_x64_gen1/13.39.06",
            "/galleries/gallery/images/ubuntu-22.04-gen2/versions/99.0.0",
            "https://account.blob.core.windows.net/vhds/ubuntu-22.04.vhd?sv=24.04",
        ]
        for key in ("shared_gallery", "community_gallery_image", "vhd", "image"):
            for image in images:
                with self.subTest(key=key, image=image):
                    target = infer_target_os_info({key: image})
                    assert target
                    self.assertEqual(parse_version("22.04"), target.version)

    def test_unknown_conflicting_and_non_ubuntu_versions(self) -> None:
        images = [
            "Canonical UbuntuServer custom 22.04.202307140",
            "Canonical UbuntuServer kernel-22.04 latest",
            "Canonical UbuntuServer 22_99-lts latest",
            "Canonical ubuntu-24_04-lts 22_04-lts latest",
            "Canonical ubuntu-server-jammy 24_04-lts latest",
            "/galleries/jammy/images/ubuntu-custom/versions/22.04.0",
            "/images/ubuntu-linux-azure_6.8.0-1071.79.22.04.1/versions/22.04",
            "Canonical UbuntuServer 22_04-lts latest,"
            "Canonical UbuntuServer 24_04-lts latest",
            "redhat rhel 9_5 latest",
            "debian debian-12 12-gen2 latest",
        ]
        for image in images:
            with self.subTest(image=image):
                target = infer_target_os_info({"image": image})
                assert target
                self.assertIsNone(target.version)

    def test_source_precedence_does_not_mix_versions(self) -> None:
        target = infer_target_os_info(
            {
                "marketplace_image": "Canonical UbuntuServer custom latest",
                "shared_gallery": "/images/ubuntu-24.04/versions/1.0.0",
            }
        )
        assert target
        self.assertIsNone(target.version)

    def test_version_boundaries(self) -> None:
        restriction = OsRequirement(Ubuntu, min_version="22.04", max_version="24.04")
        for allow in (True, False):
            case = _build_case(
                "versioned",
                **{"supported_os" if allow else "unsupported_os": [restriction]},
            )
            for release, matches in (
                ("20.04", False),
                ("22.04", True),
                ("22.04.5", True),
                ("23.10", True),
                ("24.04", False),
                ("26.04", False),
            ):
                with self.subTest(allow=allow, release=release):
                    self.assertEqual(
                        matches if allow else not matches,
                        _is_os_compatible(case, Ubuntu, parse_version(release)),
                    )
            self.assertTrue(_is_os_compatible(case, Ubuntu))
            self.assertTrue(_is_os_compatible(case, Linux))
            self.assertTrue(_is_os_compatible(case, Debian))

    def test_mixed_entries_and_non_ubuntu_targets(self) -> None:
        case = _build_case(
            "exclude",
            unsupported_os=[OsRequirement(Ubuntu, max_version="22.04"), Oracle],
        )
        for target in (Suse, CBLMariner, Debian):
            self.assertTrue(_is_os_compatible(case, target, parse_version("8.0")))
        self.assertFalse(_is_os_compatible(case, Oracle))
        case = _build_case(
            "ubuntu_only_exclusion",
            unsupported_os=[OsRequirement(Ubuntu, max_version="22.04")],
        )
        self.assertTrue(_is_os_compatible(case, Redhat, parse_version("8.0")))
        case = _build_case(
            "include",
            supported_os=[OsRequirement(Ubuntu, min_version="22.04"), Debian],
        )
        self.assertTrue(_is_os_compatible(case, Ubuntu, parse_version("20.04")))
        case = _build_case(
            "exclude_all",
            unsupported_os=[OsRequirement(Ubuntu, min_version="22.04"), Ubuntu],
        )
        self.assertFalse(_is_os_compatible(case, Ubuntu))

    def test_invalid_declarations(self) -> None:
        for value in (
            "",
            "22",
            "22.4",
            "22.04.1",
            ">=22.04",
            "junk22.04",
            "22.00",
            "22.13",
        ):
            with self.subTest(value=value), self.assertRaises(LisaException):
                OsRequirement(Ubuntu, min_version=value)
        for minimum in ("22.04", "24.04"):
            with self.assertRaises(LisaException):
                OsRequirement(Ubuntu, min_version=minimum, max_version="22.04")
        for distro in (Debian, Linux, Redhat):
            with self.assertRaisesRegex(LisaException, "Ubuntu only"):
                OsRequirement(distro, min_version="22.04")
        with self.assertRaises(LisaException):
            simple_requirement(
                supported_os=[Ubuntu],
                unsupported_os=[OsRequirement(Ubuntu, max_version="22.04")],
            )

    def test_requirement_repr(self) -> None:
        cases = [
            (OsRequirement(Ubuntu), "Ubuntu"),
            (OsRequirement(Ubuntu, min_version="20.04"), "Ubuntu[>=20.04)"),
            (OsRequirement(Ubuntu, max_version="24.04"), "Ubuntu[<24.04)"),
            (
                OsRequirement(Ubuntu, min_version="20.04", max_version="24.04"),
                "Ubuntu[>=20.04,<24.04)",
            ),
        ]
        for entry, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, repr(entry))
                self.assertEqual(expected, str(entry))
        # Skip reasons render the os_type SetSpace, which uses each item's repr.
        requirement = simple_requirement(
            supported_os=[OsRequirement(Ubuntu, min_version="20.04")]
        )
        self.assertIn("Ubuntu[>=20.04)", str(requirement.os_type))

    def test_requirement_helpers_and_inheritance(self) -> None:
        entry = OsRequirement(Ubuntu, min_version="22.04")
        for requirement in (
            simple_requirement(supported_os=[entry]),
            node_requirement(schema.NodeSpace(), supported_os=[entry]),
        ):
            suite = TestSuiteMetadata(
                area="version",
                category="functional",
                description="version",
                requirement=requirement,
            )
            case = TestCaseMetadata(description="inherited")
            case.suite = suite
            self.assertFalse(_is_os_compatible(case, Ubuntu, parse_version("20.04")))
            case.requirement = simple_requirement(supported_os=[Ubuntu])
            self.assertTrue(_is_os_compatible(case, Ubuntu, parse_version("20.04")))

    def test_gate_and_selection(self) -> None:
        case = _build_case(
            "old_ubuntu", unsupported_os=[OsRequirement(Ubuntu, max_version="22.04")]
        )
        for gate in (None, False, "", "false", True, "YES", "1"):
            variables: Dict[str, Any] = {
                "enable_distro_pre_filtering": gate,
                "marketplace_image": "Canonical UbuntuServer 20_04-lts latest",
            }
            for wrapped in (False, True):
                values: Dict[str, Any] = (
                    {
                        name: VariableEntry(name, value)
                        for name, value in variables.items()
                    }
                    if wrapped
                    else variables
                )
                target = resolve_target_os(values)
                results = select_testcases(
                    init_cases=[case],
                    target_os=target.os_type if target else None,
                    target_os_version=target.version if target else None,
                )
                self.assertEqual(0 if gate in (True, "YES", "1") else 1, len(results))

    def test_runner_and_list_pass_same_version(self) -> None:
        variables = {
            "enable_distro_pre_filtering": VariableEntry("gate", True),
            "marketplace_image": VariableEntry(
                "image", "Canonical ubuntu-24_04-lts server latest"
            ),
        }
        builder = Mock()
        builder.variables = variables
        builder.partial_resolve.return_value = []
        runbook = schema.Runbook()
        runbook.platform = [schema.Platform(type="ready")]
        runner = LisaRunner(builder, runbook, 0, {})
        # Stop immediately after selection, before platform initialization.
        with patch("lisa.runner.BaseRunner._initialize"), patch(
            "lisa.runners.lisa_runner.select_testcases",
            side_effect=RuntimeError("selection captured"),
        ) as runner_select:
            with self.assertRaisesRegex(RuntimeError, "selection captured"):
                runner._initialize()
        for list_all in (False, True):
            with patch(
                "lisa.commands.RunbookBuilder.from_path", return_value=builder
            ), patch("lisa.commands.select_testcases", return_value=[]) as list_select:
                commands.list_start(
                    Namespace(
                        runbook="unused", variables=[], list_all=list_all, type="case"
                    )
                )
            for key in ("target_os", "target_os_version"):
                self.assertEqual(
                    runner_select.call_args.kwargs[key],
                    list_select.call_args.kwargs[key],
                )
        self.assertEqual(
            parse_version("24.04"), runner_select.call_args.kwargs["target_os_version"]
        )


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

    def test_short_aliases_require_token_boundary(self) -> None:
        # Short aliases ('ol', 'azl', 'bsd') must not match as midword
        # substrings inside unrelated names.
        false_positive_cases = [
            "golden-image.vhd",  # contains 'ol' inside 'golden'
            "polkit-base-v1.vhd",  # contains 'ol' inside 'polkit'
            "lambsdale.vhd",  # contains 'bsd' inside 'lambsdale'
        ]
        for image in false_positive_cases:
            self.assertIsNone(
                _infer_from_image_string(image),
                msg=f"unexpected match for image={image}",
            )

        # Legitimate prefix uses (alias followed by version digits or a
        # separator) must still match.
        legitimate_cases = {
            "ol9-lvm-gen2": Oracle,
            "ol-base.vhd": Oracle,
            "azl3-base": CBLMariner,
            "azl-image.vhd": CBLMariner,
        }
        for image, expected in legitimate_cases.items():
            self.assertIs(
                _infer_from_image_string(image),
                expected,
                msg=f"image={image}",
            )

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

    def test_target_azure_drops_hyperv_cases(self) -> None:
        cases = [
            _build_case("any_platform"),
            _build_case("azure_only", supported_platform_type=[AZURE]),
            _build_case("hyperv_only", supported_platform_type=[HYPERV]),
            _build_case("not_azure", unsupported_platform_type=[AZURE]),
        ]

        results = select_testcases(
            filters=None, init_cases=cases, target_platforms=[AZURE]
        )

        self.assertEqual(
            sorted(result.name for result in results),
            ["any_platform", "azure_only"],
        )
        self.assertTrue(_is_platform_compatible(cases[2], [AZURE, HYPERV]))
        self.assertFalse(_is_platform_compatible(cases[3], [AZURE]))
        self.assertTrue(_is_platform_compatible(cases[3], [HYPERV]))


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
