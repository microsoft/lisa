# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import csv
from argparse import Namespace
from collections import Counter
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import OsRequirement, commands, schema
from lisa.environment import EnvironmentStatus
from lisa.operating_system import (
    CBLMariner,
    CentOs,
    Fedora,
    Linux,
    Oracle,
    OsInformation,
    Redhat,
    Suse,
)
from lisa.runners.lisa_runner import LisaRunner
from lisa.search_space import ResultReason
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import TestCaseRuntimeData, TestResult
from lisa.util import LisaException, SkippedException, parse_version
from lisa.util.os_requirement import matches_os_requirement
from lisa.util.os_resolver import infer_target_os_info, resolve_target_os
from lisa.variable import VariableEntry
from selftests.test_distro_prefilter import _build_case


class OsVersionPrefilterTestCase(TestCase):
    def test_complete_image_corpus(self) -> None:
        with (Path(__file__).parent / "azure" / "os_images.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(311, len(rows))
        self.assertEqual(311, len({row["image"].lower() for row in rows}))
        self.assertEqual(
            {"major": 42, "minor": 269}, Counter(row["precision"] for row in rows)
        )
        for row in rows:
            for image in (row["image"], ":".join(row["image"].split())):
                with self.subTest(image=image):
                    target = infer_target_os_info({"marketplace_image": image})
                    assert target
                    self.assertEqual(row["os_type"], target.os_type.__name__)
                    self.assertEqual(parse_version(row["release"]), target.version)
                    self.assertEqual(row["precision"], target.version_precision)

    def test_release_bounds_and_precision(self) -> None:
        for distro in (Redhat, CBLMariner):
            for allow in (True, False):
                case = _build_case(
                    "release",
                    **{
                        "supported_os"
                        if allow
                        else "unsupported_os": [
                            OsRequirement(distro, min_version="8.3", max_version="8.10")
                        ]
                    },
                )
                for version, matches in (
                    ("8.2", False),
                    ("8.3", True),
                    ("8.9.5", True),
                    ("8.10", False),
                    ("9.0", False),
                ):
                    self.assertEqual(
                        matches if allow else not matches,
                        _is_os_compatible(case, distro, parse_version(version)),
                    )
                self.assertTrue(_is_os_compatible(case, distro))
                self.assertTrue(
                    _is_os_compatible(case, distro, parse_version("8"), "major")
                )
        for minimum, maximum, major, expected in (
            ("3.0", "4.0", "3", True),
            ("3.0", "4.0", "4", False),
            ("3.1", "4.0", "3", None),
            ("3.0", "3.1", "3", None),
            ("4.0", None, "3", False),
            (None, "3.0", "3", False),
        ):
            entry = OsRequirement(CBLMariner, minimum, maximum)
            self.assertIs(
                expected,
                matches_os_requirement(
                    entry,
                    CBLMariner,
                    parse_version(major),
                    prefilter=True,
                    version_precision="major",
                ),
            )

    def test_concrete_release_domains(self) -> None:
        entry = OsRequirement(Redhat, max_version="8.3")
        for child in (CentOs, Oracle):
            self.assertIs(
                False, matches_os_requirement(entry, child, parse_version("7"))
            )
            self.assertIs(True, matches_os_requirement(Redhat, child))
        for broad in (Fedora, Linux):
            self.assertIsNone(
                matches_os_requirement(entry, broad, parse_version("7"), prefilter=True)
            )

    def test_invalid_new_bounds(self) -> None:
        for distro in (Redhat, CBLMariner):
            for value in ("3", "03.0", "3.00", "3.0.1", "3.-1", "3.x", ""):
                with self.subTest(value=value), self.assertRaises(LisaException):
                    OsRequirement(distro, min_version=value)
            for maximum in ("3.0", "2.9"):
                with self.assertRaises(LisaException):
                    OsRequirement(distro, min_version="3.0", max_version=maximum)

    def test_unknown_and_conflicting_images(self) -> None:
        for image in (
            "redhat rhel kernel-8.10 latest",
            "redhat rhel 810-unknown latest",
            "redhat custom 810-gen2 latest",
            "redhat rhel custom 8.10.20261023",
            "microsoftazurelinux azurelinux-4 3 latest",
            "MicrosoftCBLMariner azure-linux-3 azure-linux-4 latest",
            "MicrosoftCBLMariner cbl-mariner-test custom 2.0.20260101",
            "redhat rhel 8_10 latest,redhat rhel 9_5 latest",
        ):
            with self.subTest(image=image):
                target = infer_target_os_info({"marketplace_image": image})
                assert target
                self.assertIsNone(target.version)

    def test_custom_names_and_sanitized_logs(self) -> None:
        for key in ("shared_gallery", "community_gallery_image", "vhd", "image"):
            for name, distro, release in (
                ("rhel-8.10-x64-gen2", Redhat, "8.10"),
                ("rhel_8_10_arm64_gen2", Redhat, "8.10"),
                ("azurelinux-4.0-arm64-gen2", CBLMariner, "4.0"),
                ("cblmariner-2.0-x64-gen2", CBLMariner, "2.0"),
            ):
                for image in (
                    f"/galleries/ignored/images/{name}/versions/99.0.0",
                    f"subscription/group/gallery/{name}/99.0.0",
                    f"https://account.blob.core.windows.net/vhds/{name}.vhd?sig=SECRET",
                ):
                    with self.subTest(key=key, image=image), patch(
                        "lisa.util.os_resolver._log"
                    ) as log:
                        target = infer_target_os_info({key: image})
                        assert target
                        self.assertIs(distro, target.os_type)
                        self.assertEqual(parse_version(release), target.version)
                        self.assertEqual("minor", target.version_precision)
                        self.assertNotIn("SECRET", str(log.mock_calls))
                        self.assertNotIn("account.blob", str(log.mock_calls))
        for image in (
            "/galleries/rhel-8.10/images/rhel-custom/versions/8.10",
            "https://host/vhds/rhel-custom.vhd?release=8.10",
            "/images/rhel-linux-azure_6.8.0-1071.79.8.10/versions/8.10",
            "/images/rhel-8.10-rhel-9.5/versions/1",
            "/images/azurelinux-3.0-rhel-8.10/versions/1",
        ):
            with self.subTest(image=image):
                target = infer_target_os_info({"image": image})
                self.assertTrue(target is None or target.version is None)

    def test_source_identity_and_other_distro_fallback(self) -> None:
        for image in (
            "https://ubuntu.example/vhds/rhel-8.10.vhd?sig=SECRET",
            "/galleries/ubuntu/images/rhel-8.10/versions/99.0",
        ):
            target = infer_target_os_info({"image": image})
            assert target
            self.assertIs(Redhat, target.os_type)
            self.assertEqual(parse_version("8.10"), target.version)
        for image in (
            "redhat ubuntu-24_04-lts 8_10 latest",
            "/images/rhel-8.10-ubuntu-22.04/versions/1",
        ):
            self.assertIsNone(infer_target_os_info({"image": image}))
        target = infer_target_os_info(
            {"marketplace_image": "suse sles-15-sp6 gen2 latest"}
        )
        assert target
        self.assertIs(Suse, target.os_type)
        self.assertIsNone(target.version)
        target = infer_target_os_info(
            {
                "marketplace_image": "redhat rhel custom latest",
                "shared_gallery": "/images/rhel-8.10/versions/1",
            }
        )
        assert target
        self.assertIsNone(target.version)

    def test_unrelated_guest_does_not_read_release(self) -> None:
        case = _build_case(
            "unrelated", unsupported_os=[OsRequirement(Redhat, max_version="8.0")]
        )
        node = Mock()
        node.os = CentOs(node)
        environment = Mock()
        environment.status = EnvironmentStatus.Connected
        environment.nodes.list.return_value = [node]
        requirement = case.requirement.environment
        assert requirement
        with patch.object(
            requirement, "check", return_value=ResultReason()
        ), patch.object(
            node.os, "_get_information", side_effect=AssertionError("unneeded release")
        ):
            result = TestResult("unrelated", TestCaseRuntimeData(case))
            self.assertTrue(result.check_environment(environment))

    def test_guest_release_is_enforced_without_prefilter(self) -> None:
        for distro in (CBLMariner, Redhat):
            case = _build_case(
                "runtime", unsupported_os=[OsRequirement(distro, max_version="3.0")]
            )
            for version in ("2.0", "3.0"):
                node = Mock()
                node.os = distro(node)
                node.os._information = OsInformation(
                    version=parse_version(version), vendor=distro.__name__
                )
                environment = Mock()
                environment.status = EnvironmentStatus.Connected
                environment.nodes.list.return_value = [node]
                result = TestResult("release", TestCaseRuntimeData(case))
                requirement = case.requirement.environment
                assert requirement
                with patch.object(requirement, "check", return_value=ResultReason()):
                    if version == "2.0":
                        with self.assertRaises(SkippedException):
                            result.check_environment(environment)
                    else:
                        self.assertTrue(result.check_environment(environment))

    def test_major_precision_gate_runner_and_listing(self) -> None:
        case = _build_case(
            "partial", unsupported_os=[OsRequirement(CBLMariner, max_version="4.1")]
        )
        raw = {"marketplace_image": "microsoftazurelinux azurelinux-4 4 latest"}
        for enabled in (False, True):
            target = resolve_target_os(dict(raw, enable_distro_pre_filtering=enabled))
            self.assertEqual(
                1,
                len(
                    select_testcases(
                        init_cases=[case],
                        target_os=target.os_type if target else None,
                        target_os_version=target.version if target else None,
                        target_os_version_precision=target.version_precision
                        if target
                        else "minor",
                    )
                ),
            )
        builder = Mock()
        builder.variables = {
            name: VariableEntry(name, value)
            for name, value in dict(raw, enable_distro_pre_filtering=True).items()
        }
        builder.partial_resolve.return_value = []
        runbook = schema.Runbook()
        runbook.platform = [schema.Platform(type="ready")]
        runner = LisaRunner(builder, runbook, 0, {})
        with patch("lisa.runner.BaseRunner._initialize"), patch(
            "lisa.runners.lisa_runner.select_testcases",
            side_effect=RuntimeError("selection captured"),
        ) as selected:
            with self.assertRaisesRegex(RuntimeError, "selection captured"):
                runner._initialize()
        self.assertEqual(
            "major", selected.call_args.kwargs["target_os_version_precision"]
        )
        for list_all in (False, True):
            with patch(
                "lisa.commands.RunbookBuilder.from_path", return_value=builder
            ), patch("lisa.commands.select_testcases", return_value=[]) as listed:
                commands.list_start(
                    Namespace(
                        runbook="unused", variables=[], list_all=list_all, type="case"
                    )
                )
            for key in (
                "target_os",
                "target_os_version",
                "target_os_version_precision",
            ):
                self.assertEqual(
                    selected.call_args.kwargs[key], listed.call_args.kwargs[key]
                )
