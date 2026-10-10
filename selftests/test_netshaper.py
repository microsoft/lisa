from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Callable, List, Tuple
from unittest import TestCase
from unittest.mock import Mock, patch

from assertpy import assert_that

from lisa.operating_system import BSD, CBLMariner, Linux, Posix, Windows
from lisa.tools.git import Git
from lisa.tools.make import Make
from lisa.tools.netshaper import NetShaper
from lisa.util import LisaException, SkippedException, UnsupportedOperationException


class NetShaperTestCase(TestCase):
    def setUp(self) -> None:
        self.node = Mock()
        self.tool = NetShaper(self.node)
        run_patch = patch.object(self.tool, "run")
        self.run_mock = run_patch.start()
        self.run_mock.return_value = Mock(exit_code=0, stdout="", stderr="")
        self.addCleanup(run_patch.stop)

    def test_commands(self) -> None:
        self.tool.set_shaper("ens1", 100000000, "netdev", 1, "bps")
        self.run_mock.assert_called_with(
            "set dev ens1 handle scope netdev id 1 bw-max 100000000bit",
            sudo=True,
            force_run=True,
        )
        self.tool.set_shaper("ens1", 100000000, "netdev", 2, "bps")
        assert_that(self.run_mock.call_args.args[0]).contains("id 2")
        self.tool.delete_shaper("ens1", "netdev", 1)
        self.run_mock.assert_called_with(
            "delete dev ens1 handle scope netdev id 1", sudo=True, force_run=True
        )

    def test_show_rates(self) -> None:
        for value, expected in (
            ("800bit", "800"),
            ("1.25Kbit", "1250"),
            ("100Mbit", "100000000"),
            ("1.5Gbit", "1500000000"),
            ("1Tbit", "1000000000000"),
        ):
            with self.subTest(value=value):
                self.run_mock.return_value = Mock(
                    exit_code=0,
                    stderr="",
                    stdout=(
                        f"dev: ens1 scope netdev id 1 bw-max {value} bw-min 8bit\n"
                    ),
                )
                shapers = self.tool.get_shapers("ens1", "netdev", 1)
                assert_that(shapers).is_length(1)
                assert_that(shapers[0].bw_max).is_equal_to(Decimal(expected))
                assert_that(shapers[0].bw_min).is_equal_to(Decimal(8))
                assert_that(shapers[0].id).is_equal_to(1)
                self.run_mock.assert_called_with(
                    "show dev ens1 handle scope netdev id 1",
                    sudo=True,
                    force_run=True,
                )

    def test_absent_shaper(self) -> None:
        self.run_mock.return_value = Mock(
            exit_code=255,
            stderr="RTNETLINK answers: No such file or directory",
            stdout="Kernel command failed: -2",
        )
        assert_that(self.tool.get_shapers("ens1", "netdev", 1)).is_empty()

    def test_errors_are_not_absence(self) -> None:
        for message, exception in (
            ("Failed to resolve net_shaper", SkippedException),
            ("Cannot resolve net_shaper", SkippedException),
            ("net_shaper not found", SkippedException),
            (
                "RTNETLINK answers: No such file or directory\n"
                "Error talking to the kernel",
                SkippedException,
            ),
            (
                "RTNETLINK answers: Operation not supported",
                SkippedException,
            ),
            ("net_shaper operation not supported", SkippedException),
            ("RTNETLINK answers: Operation not permitted", LisaException),
            ("Device ens1 not found", LisaException),
            ("No such file or directory", LisaException),
        ):
            with self.subTest(message=message):
                self.run_mock.return_value = Mock(
                    exit_code=1, stderr=message, stdout="Kernel command failed: -1"
                )
                with self.assertRaises(exception):
                    self.tool.get_shapers("ens1", "netdev", 1)
                assert_that(self.tool.get_error(self.run_mock.return_value)).contains(
                    message, "Kernel command failed: -1"
                )

    def test_invalid_show_output(self) -> None:
        for output in (
            "",
            "{}",
            "dev: ens1 scope netdev bw-max 100",
            "dev: ens1 scope netdev bw-max nope",
            "dev: ens1 scope netdev id 2 bw-max 100Mbit",
            "dev: ens1 scope queue id 1 bw-max 100Mbit",
            "dev: other scope netdev id 1 bw-max 100Mbit",
            "dev: ens1 scope netdev id 1 weight 1 weight 2",
            "dev: ens1 scope netdev id 1 parent-scope unknown",
            "dev: ens1 scope netdev id 1 parent-id nope",
        ):
            with self.subTest(output=output):
                self.run_mock.return_value = Mock(exit_code=0, stdout=output, stderr="")
                with self.assertRaises(LisaException):
                    self.tool.get_shapers("ens1", "netdev", 1)

    def test_netdev_readback_without_id(self) -> None:
        output = "dev: ens1 scope netdev bw-max 100Mbit"
        self.run_mock.return_value = Mock(exit_code=0, stdout=output, stderr="")
        shapers = self.tool.get_shapers("ens1", "netdev", 1)
        assert_that(shapers).is_length(1)
        assert_that(shapers[0].scope).is_equal_to("netdev")
        assert_that(shapers[0].id).is_none()
        assert_that(shapers[0].bw_max).is_equal_to(Decimal(100000000))
        assert_that(shapers[0].raw).is_equal_to(output)
        self.run_mock.assert_called_once_with(
            "show dev ens1 handle scope netdev id 1", sudo=True, force_run=True
        )

    def test_node_queue_readback_requires_id(self) -> None:
        for scope in ("node", "queue"):
            with self.subTest(scope=scope):
                self.run_mock.return_value = Mock(
                    exit_code=0,
                    stdout=f"dev: ens1 scope {scope} bw-max 100Mbit",
                    stderr="",
                )
                with self.assertRaises(LisaException):
                    self.tool.get_shapers("ens1", scope, 1)

    def test_explicit_readback_id_must_match(self) -> None:
        for scope in ("netdev", "node", "queue"):
            with self.subTest(scope=scope):
                self.run_mock.return_value = Mock(
                    exit_code=0,
                    stdout=f"dev: ens1 scope {scope} id 2 bw-max 100Mbit",
                    stderr="",
                )
                with self.assertRaises(LisaException):
                    self.tool.get_shapers("ens1", scope, 1)

    def test_metric_rejected(self) -> None:
        with self.assertRaisesRegex(
            UnsupportedOperationException, "upstream CLI upgrade"
        ):
            self.tool.set_shaper("ens1", 100, "queue", 7, "pps")
        self.run_mock.assert_not_called()

    def test_generic_handles(self) -> None:
        for scope, shaper_id in (("queue", 7), ("node", 42)):
            with self.subTest(scope=scope):
                self.tool.set_shaper("ens1", 800, scope, shaper_id, "bps")
                self.run_mock.assert_called_with(
                    f"set dev ens1 handle scope {scope} id {shaper_id} bw-max 800bit",
                    sudo=True,
                    force_run=True,
                )
                self.run_mock.return_value = Mock(
                    exit_code=0,
                    stderr="",
                    stdout=(
                        f"dev: ens1 scope {scope} id {shaper_id} "
                        "parent-scope node parent-id 9 bw-max 800bit weight 3"
                    ),
                )
                shapers = self.tool.get_shapers("ens1", scope, shaper_id)
                self.run_mock.assert_called_with(
                    f"show dev ens1 handle scope {scope} id {shaper_id}",
                    sudo=True,
                    force_run=True,
                )
                assert_that(shapers).is_length(1)
                assert_that(shapers[0].scope).is_equal_to(scope)
                assert_that(shapers[0].id).is_equal_to(shaper_id)
                assert_that(shapers[0].parent_scope).is_equal_to("node")
                assert_that(shapers[0].parent_id).is_equal_to(9)
                assert_that(shapers[0].weight).is_equal_to(3)
                self.tool.delete_shaper("ens1", scope, shaper_id)
                self.run_mock.assert_called_with(
                    f"delete dev ens1 handle scope {scope} id {shaper_id}",
                    sudo=True,
                    force_run=True,
                )

    def test_required_parameters(self) -> None:
        calls: List[Tuple[Callable[..., Any], Tuple[Any, ...]]] = [
            (self.tool.get_shapers, ("ens1",)),
            (self.tool.get_shapers, ("ens1", "queue")),
            (self.tool.delete_shaper, ("ens1",)),
            (self.tool.delete_shaper, ("ens1", "node")),
            (self.tool.set_shaper, ("ens1", 800)),
            (self.tool.set_shaper, ("ens1", 800, "queue")),
            (self.tool.set_shaper, ("ens1", 800, "queue", 7)),
        ]
        for method, arguments in calls:
            with self.subTest(method=method.__name__, arguments=arguments):
                with self.assertRaises(TypeError):
                    method(*arguments)
        self.run_mock.assert_not_called()

    def test_mutations_preserve_rejection_results(self) -> None:
        result = Mock(exit_code=1, stderr="Operation not permitted", stdout="")
        self.run_mock.return_value = result
        assert_that(self.tool.set_shaper("ens1", 800, "node", 9, "bps")).is_same_as(
            result
        )
        assert_that(self.tool.delete_shaper("ens1", "node", 9)).is_same_as(result)

    def test_unsupported_set_skips(self) -> None:
        for message in (
            "RTNETLINK answers: Operation not supported",
            "net_shaper operation not supported",
        ):
            with self.subTest(message=message):
                result = Mock(exit_code=1, stderr=message, stdout="")
                self.run_mock.return_value = result
                with self.assertRaises(SkippedException):
                    self.tool.set_shaper("ens1", 100000000, "netdev", 1, "bps")
                assert_that(self.tool.delete_shaper("ens1", "netdev", 1)).is_same_as(
                    result
                )

    def test_reported_precision(self) -> None:
        assert_that(self.tool._parse_rate("100Mbit").as_tuple().exponent).is_equal_to(6)
        assert_that(self.tool._parse_rate("1.25Kbit").as_tuple().exponent).is_equal_to(
            1
        )

    def test_existing_binary_requires_fresh_install(self) -> None:
        self.tool.initialize()
        with patch.object(self.tool, "command_exists", return_value=(True, False)):
            assert_that(self.tool._check_exists()).is_false()

    def test_install_requires_linux(self) -> None:
        for operating_system in (Posix, BSD, Windows):
            with self.subTest(operating_system=operating_system.__name__):
                self.node.os = Mock(spec=operating_system)
                assert_that(self.tool.can_install).is_false()
                with self.assertRaisesRegex(UnsupportedOperationException, "Linux"):
                    self.tool._install()
                self.node.execute.assert_not_called()
        self.node.os = Mock(spec=Linux)
        assert_that(self.tool.can_install).is_true()

    def test_azure_linux_build_dependencies(self) -> None:
        self.tool.initialize()
        self.node.os = Mock(spec=CBLMariner)
        self.node.os.is_package_in_repo.return_value = True
        source = PurePosixPath("/tools/netshaper/iproute2")
        git = Mock()
        git.clone.return_value = source
        git.run.return_value = Mock(stdout="upstream-revision")
        self.node.tools = {Git: git, Make: Mock()}
        self.run_mock.return_value = Mock(stdout="netshaper utility, upstream-version")
        timeline = Mock()
        timeline.attach_mock(self.node.os.install_packages, "install_packages")
        timeline.attach_mock(self.node.execute, "execute")
        with patch.object(
            self.tool, "get_tool_path", return_value=source.parent
        ), patch.object(self.tool, "command_exists", return_value=(True, False)):
            assert_that(self.tool._install()).is_true()
        assert_that(timeline.mock_calls[0].args[0]).is_equal_to(
            ["glibc-devel", "binutils", "kernel-headers"]
        )

    def test_source_install_order(self) -> None:
        self.tool.initialize()
        self.node.os = Mock(spec=Linux)
        self.node.os.is_package_in_repo.return_value = True
        source = PurePosixPath("/tools/netshaper/iproute2")
        git = Mock()
        git.clone.return_value = source
        git.run.return_value = Mock(stdout="upstream-revision")
        make = Mock()
        self.node.tools = {Git: git, Make: make}
        self.run_mock.return_value = Mock(stdout="netshaper utility, upstream-version")
        timeline = Mock()
        timeline.attach_mock(self.node.execute, "execute")
        timeline.attach_mock(make.make, "make")
        with patch.object(
            self.tool, "get_tool_path", return_value=source.parent
        ), patch.object(self.tool, "command_exists", return_value=(True, False)):
            assert_that(self.tool._install()).is_true()
        git.run.assert_any_call(
            "fetch origin main", cwd=source, force_run=True, expected_exit_code=0
        )
        git.checkout.assert_called_once_with("FETCH_HEAD", cwd=source)
        assert_that([event.args[0] for event in timeline.mock_calls]).is_equal_to(
            [
                "./configure",
                "PREFIX=/usr/local SBINDIR=/usr/local/sbin",
                "/tools/netshaper/iproute2/netshaper/netshaper -V",
                "install PREFIX=/usr/local SBINDIR=/usr/local/sbin",
            ]
        )
        self.node.os.install_packages.assert_any_call("libmnl-dev")
