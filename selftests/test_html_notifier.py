# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import OrderedDict
from pathlib import Path
from unittest import TestCase

from lisa.messages import TestRunMessage, TestRunStatus
from lisa.notifiers.html import Html, HtmlSchema
from lisa.secret import add_secret, mask, reset
from lisa.util import constants


class HtmlMetadataSecretTestCase(TestCase):
    """Tests that _generate_metadata_rows masks secrets in the runbook value."""

    def setUp(self) -> None:
        reset()
        self._original_runbook = constants.RUNBOOK
        self._original_log_path = constants.RUN_LOCAL_LOG_PATH

        constants.RUN_LOCAL_LOG_PATH = Path("/tmp/lisa_test")

        runbook = HtmlSchema(type="html")
        self._notifier = Html(runbook=runbook)
        self._notifier._initialize()

    def tearDown(self) -> None:
        reset()
        constants.RUNBOOK = self._original_runbook
        constants.RUN_LOCAL_LOG_PATH = self._original_log_path

    def test_metadata_rows_masks_runbook_secrets(self) -> None:
        """Secrets registered after metadata initialization are masked at render."""
        raw_runbook = (
            "{'notifier': [{'type': 'log_agent', "
            "'azure_openai_api_key': 'my-super-secret-token'}]}"
        )
        self._notifier._metadata = OrderedDict(
            {
                "test project": "some project",
                "runbook": raw_runbook,
            }
        )

        # Register the secret AFTER metadata is stored (simulates late registration)
        add_secret("my-super-secret-token", sub="******")

        result = self._notifier._generate_metadata_rows()

        self.assertIn("some project", result)
        self.assertNotIn("my-super-secret-token", result)
        self.assertIn("******", result)

    def test_metadata_rows_masks_multiple_secrets_in_runbook(self) -> None:
        """Multiple secrets within the runbook value are all masked."""
        raw_runbook = (
            "{'platform': [{'admin_password': 'P@ssw0rd!', "
            "'credential': {'token': 'bearer-token-xyz'}}]}"
        )
        self._notifier._metadata = OrderedDict({"runbook": raw_runbook})

        add_secret("P@ssw0rd!", sub="***pwd***")
        add_secret("bearer-token-xyz", sub="***tok***")

        result = self._notifier._generate_metadata_rows()

        self.assertNotIn("P@ssw0rd!", result)
        self.assertNotIn("bearer-token-xyz", result)
        self.assertIn("***pwd***", result)
        self.assertIn("***tok***", result)

    def test_metadata_rows_html_escapes_after_masking(self) -> None:
        """HTML escaping is applied after masking, so masked output is safe."""
        raw_runbook = "{'key': '<script>alert(1)</script>'}"
        self._notifier._metadata = OrderedDict({"runbook": raw_runbook})

        result = self._notifier._generate_metadata_rows()

        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_early_mask_plus_late_secret_both_applied(self) -> None:
        """Simulates the real flow: early mask catches some, post-mask catches rest."""
        add_secret("early-secret", sub="***early***")

        raw_runbook = mask("{'early_key': 'early-secret', 'late_key': 'late-secret'}")
        self.assertNotIn("early-secret", raw_runbook)  # masked
        self.assertIn("late-secret", raw_runbook)  # not (yet) masked

        self._notifier._metadata = OrderedDict({"runbook": raw_runbook})

        add_secret("late-secret", sub="***late***")

        result = self._notifier._generate_metadata_rows()

        self.assertNotIn("early-secret", result)
        self.assertNotIn("late-secret", result)
        self.assertIn("***early***", result)
        self.assertIn("***late***", result)


class HtmlStructuredRunbookTestCase(TestCase):
    """Regression tests: dict/list-backed constants.RUNBOOK must not raise TypeError."""

    def setUp(self) -> None:
        reset()
        self._original_runbook = constants.RUNBOOK
        self._original_log_path = constants.RUN_LOCAL_LOG_PATH
        self._had_runbook_file = hasattr(constants, "RUNBOOK_FILE")
        self._original_runbook_file = getattr(constants, "RUNBOOK_FILE", None)

        constants.RUN_LOCAL_LOG_PATH = Path("/tmp/lisa_test")
        constants.RUNBOOK_FILE = Path("/tmp/lisa_test/runbook.yml")

        runbook = HtmlSchema(type="html")
        self._notifier = Html(runbook=runbook)
        self._notifier._initialize()

    def tearDown(self) -> None:
        reset()
        constants.RUNBOOK = self._original_runbook
        constants.RUN_LOCAL_LOG_PATH = self._original_log_path
        if self._had_runbook_file:
            constants.RUNBOOK_FILE = self._original_runbook_file
        elif hasattr(constants, "RUNBOOK_FILE"):
            del constants.RUNBOOK_FILE

    def _send_initializing_message(self) -> None:
        msg = TestRunMessage(
            status=TestRunStatus.INITIALIZING,
            run_name="test-run",
        )
        self._notifier._received_test_run(msg)

    def test_dict_runbook_does_not_raise(self) -> None:
        """A dict-backed RUNBOOK must not raise TypeError during message handling."""
        constants.RUNBOOK = {
            "notifier": [{"type": "html"}],
            "platform": [{"type": "mock"}],
        }
        # Must not raise TypeError when mask() is called on the stringified runbook
        try:
            self._send_initializing_message()
        except TypeError as e:
            self.fail(f"_received_test_run raised TypeError for dict runbook: {e}")

        result = self._notifier._generate_metadata_rows()
        self.assertIn("notifier", result)
        self.assertIn("html", result)

    def test_list_runbook_does_not_raise(self) -> None:
        """A list-backed RUNBOOK must not raise TypeError during message handling."""
        constants.RUNBOOK = [
            {"notifier": [{"type": "html"}]},
            {"platform": [{"type": "mock"}]},
        ]
        try:
            self._send_initializing_message()
        except TypeError as e:
            self.fail(f"_received_test_run raised TypeError for list runbook: {e}")

        result = self._notifier._generate_metadata_rows()
        self.assertIn("notifier", result)

    def test_none_runbook_does_not_raise(self) -> None:
        """A None RUNBOOK must not raise and should produce no runbook metadata row."""
        constants.RUNBOOK = None
        try:
            self._send_initializing_message()
        except Exception as e:
            self.fail(f"_received_test_run raised {type(e).__name__} for None runbook: {e}")

        result = self._notifier._generate_metadata_rows()
        # No runbook key should be present when value is empty/None
        self.assertNotIn(">runbook<", result)

    def test_dict_runbook_secrets_are_masked(self) -> None:
        """Secrets inside a dict-backed RUNBOOK are masked in the metadata output."""
        constants.RUNBOOK = {
            "platform": [{"admin_password": "dict-secret-password"}],
        }
        add_secret("dict-secret-password", sub="***masked***")
        self._send_initializing_message()

        result = self._notifier._generate_metadata_rows()

        self.assertNotIn("dict-secret-password", result)
        self.assertIn("***masked***", result)

    def test_list_runbook_secrets_are_masked(self) -> None:
        """Secrets inside a list-backed RUNBOOK are masked in the metadata output."""
        constants.RUNBOOK = [
            {"credential": {"token": "list-secret-token"}},
        ]
        add_secret("list-secret-token", sub="***tok***")
        self._send_initializing_message()

        result = self._notifier._generate_metadata_rows()

        self.assertNotIn("list-secret-token", result)
        self.assertIn("***tok***", result)
