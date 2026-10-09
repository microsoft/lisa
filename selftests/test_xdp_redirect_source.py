import ast
from pathlib import Path
from unittest import TestCase

from assertpy import assert_that


class XdpRedirectSourceTestCase(TestCase):
    def test_redirect_replacement_preserves_icmp_filter(self) -> None:
        source_path = (
            Path(__file__).resolve().parent.parent
            / "lisa/microsoft/testsuites/xdp/xdpdump.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        method = next(
            item
            for item in ast.walk(tree)
            if isinstance(item, ast.FunctionDef)
            and item.name == "make_on_redirect_role"
        )
        assignment = next(
            item
            for item in method.body
            if isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "redirect_block"
                for target in item.targets
            )
        )
        replacement = ast.literal_eval(assignment.value)
        assert_that(replacement).described_as(
            "Sed replacement ampersands expand to the matched preprocessor directive"
        ).does_not_contain("&")
        assert_that(replacement).contains(
            "if (pkt.l3_proto == ETH_P_IP)\\n"
            "        if (pkt.l4_proto == IPPROTO_ICMP)\\n"
            "            return bpf_redirect(XDP_REDIRECT_TARGET_IFINDEX, 0);"
        )
