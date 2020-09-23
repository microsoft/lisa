import re
from unittest.case import TestCase

from lisa.secret import PATTERN_GUID, add_secret, mask, reset
from lisa.util.logger import get_logger


class SecretTestCase(TestCase):
    def setUp(self) -> None:
        reset()

    def test_happen_twice(self) -> None:
        add_secret("test1", sub="*")
        result = mask("test1 test1 test3")
        self.assertEqual(result, "* * test3")

    def test_big_contains_small(self) -> None:
        add_secret("t1", sub="*")
        add_secret("t1t2", sub="**")
        result = mask("t1t2 t1 test3")
        self.assertEqual(result, "** * test3")

    def test_default_mask(self) -> None:
        add_secret("test1")
        result = mask("test1 test3")
        self.assertEqual(result, "****** test3")

    def test_pattern(self) -> None:
        add_secret("test", sub="*")
        add_secret(
            "f5132846-2aff-4726-baea-8c480ce9eb06",
            mask=re.compile(
                r"^([0-9a-f]{8})-(?:[0-9a-f]{4}-){3}[0-9a-f]{8}([0-9a-f]{4})$"
            ),
            sub=r"\1-****-****-****-********\2",
        )
        result = mask("my test f5132846-2aff-4726-baea-8c480ce9eb06 not")
        self.assertEqual(result, "my * f5132846-****-****-****-********eb06 not")

    def test_built_in_pattern(self) -> None:
        add_secret("test", sub="*")
        add_secret("f5132846-2aff-4726-baea-8c480ce9eb06", mask=PATTERN_GUID)
        result = mask("my test f5132846-2aff-4726-baea-8c480ce9eb06 not")
        self.assertEqual(result, "my * f5132846-****-****-****-********eb06 not")

    def test_fallback(self) -> None:
        add_secret(
            "test1",
            mask=re.compile(r"^doesn't match$"),
            sub=r"*****",
        )
        result = mask("my test1 test2 not")
        self.assertEqual(result, "my ***** test2 not")

    def test_log(self) -> None:
        add_secret("t1", sub="*")
        add_secret("t1t2", sub="**")
        log = get_logger()

        with self.assertLogs("LISA") as cm:
            log.info("t1t2 2")
        self.assertListEqual(["INFO:LISA:** 2"], cm.output)

    def test_stdout(self) -> None:
        add_secret("t1", sub="*")
        add_secret("t1t2", sub="**")

        with self.assertLogs("LISA") as cm:
            print("t1t2 2")
        self.assertListEqual(["INFO:LISA.stdout:** 2"], cm.output)

    def test_log_with_args(self) -> None:
        log = get_logger()
        add_secret("t1")
        add_secret("t2")
        with self.assertLogs("LISA") as cm:
            log.info("with args t2: %s", "t1")
        self.assertListEqual(["INFO:LISA:with args ******: ******"], cm.output)
