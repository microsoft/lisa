# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import OrderedDict
from pathlib import Path
from unittest import TestCase

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
