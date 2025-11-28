# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
AI-powered log analysis notifier for automated test failure investigation.

This module provides intelligent analysis of test failures using Azure OpenAI
to help developers quickly understand the root cause of test issues.
"""

import logging
import os
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.ai import logger as ai_logger
from lisa.ai.log_agent import analyze
from lisa.messages import MessageBase, TestResultMessage, TestStatus
from lisa.notifier import Notifier
from lisa.secret import add_secret
from lisa.util import constants, field_metadata, logger, plugin_manager


@dataclass_json()
@dataclass
class LogAgentSchema(schema.Notifier):
    """Configuration schema for the AI-powered log analysis notifier."""

    # Azure OpenAI service configuration
    azure_openai_api_key: str = field(
        default="",
        metadata=field_metadata(
            required=False,
            description="Azure OpenAI API key for authentication, if not set, will use "
            "default authentication methods.",
        ),
    )
    azure_openai_endpoint: str = field(
        default="",
        metadata=field_metadata(
            required=True, description="Azure OpenAI service endpoint URL"
        ),
    )
    embedding_endpoint: str = field(
        default="",
        metadata=field_metadata(
            required=False, description="Optional embedding service endpoint"
        ),
    )

    # AI model deployment configuration
    general_deployment_name: str = field(
        default="gpt-4o",
        metadata=field_metadata(
            description="Primary GPT model deployment name for general analysis"
        ),
    )
    software_deployment_name: str = field(
        default="gpt-4.1",
        metadata=field_metadata(
            description="Specialized GPT model deployment for software analysis"
        ),
    )

    # Analysis workflow configuration
    selected_flow: str = field(
        default="default",
        metadata=field_metadata(description="Analysis workflow type to execute"),
    )

    skip_duplicate_errors: bool = field(
        default=True,
        metadata=field_metadata(
            description="Skip analysis for errors that have already been analyzed"
        ),
    )

    def __post_init__(self) -> None:
        add_secret(self.azure_openai_api_key)


class LogAgent(Notifier):
    """
    AI-powered log analysis notifier for automated test failure investigation.

    This notifier leverages Azure OpenAI to automatically analyze failed test
    cases, providing intelligent insights into potential root causes by
    examining: - Test execution logs - Code context from the LISA

    The analysis results are attached to test result messages for consumption by
    downstream notifiers and reporting systems.

    Note: This notifier operates in pre-processing phase by the hook to ensure
    its analysis results are available to other notifiers that may depend on
    them.
    """

    @classmethod
    def type_name(cls) -> str:
        return "log_agent"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LogAgentSchema

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)
        self._analysis_results: Dict[str, str] = {}

        # Configure dedicated logging for AI operations to prevent interference
        # with test execution logs
        self._setup_ai_logging()

        # Register this instance with the plugin manager to receive hook calls
        plugin_manager.register(self)

    def _setup_ai_logging(self) -> None:
        log_file_path = os.path.join(constants.RUN_LOCAL_LOG_PATH, "ai_log_agent.log")

        ai_logger.setLevel(logging.DEBUG)

        self._log_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        self._log_handler.setLevel(logging.DEBUG)
        logger.add_handler(handler=self._log_handler, logger=ai_logger)

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestResultMessage]

    def _received_message(self, message: MessageBase) -> None:
        """
        Note: Analysis is triggered via the update_test_result_message hook
        rather than through message subscription to ensure proper timing.
        """
        pass

    def _analyze_test_failure(self, message: TestResultMessage) -> None:
        """
        Perform AI-powered analysis of a failed test case.
        Args:
            message: Test result message containing failure details and metadata.
        """
        runbook = cast(LogAgentSchema, self.runbook)

        # Skip analysis for non-failed tests
        if message.status != TestStatus.FAILED:
            return

        # Skip analysis if the same error has already been processed
        if runbook.skip_duplicate_errors and message.message in self._analysis_results:
            self._log.debug(
                f"Skipping AI analysis for test {message.full_name}({message.id_}): "
                "already processed"
            )
            message.analysis[
                "AI"
            ] = f"skip same error, refer to {self._analysis_results[message.message]}"
            return

        self._log.info(f"Initiating AI analysis for failed test: {message.full_name}")

        # cache the error message to avoid duplicate analysis
        self._analysis_results[message.message] = message.id_

        try:
            # Construct paths for log analysis
            log_folder_path = os.path.join(
                constants.RUN_LOCAL_LOG_PATH, os.path.dirname(message.log_file)
            )

            # Determine LISA framework root directory for code context
            code_path = pathlib.Path(os.path.abspath(__file__)).parent.parent.parent

            # Extract the primary error message from test output
            error_message = message.message.splitlines()[-1]

            # Execute AI-powered failure analysis
            analysis_result = analyze(
                azure_openai_endpoint=runbook.azure_openai_endpoint,
                code_path=str(code_path),
                log_folder_path=log_folder_path,
                error_message=error_message,
                azure_openai_api_key=runbook.azure_openai_api_key,
                general_deployment_name=runbook.general_deployment_name,
                software_deployment_name=runbook.software_deployment_name,
                selected_flow=runbook.selected_flow,
            )

            # Parse and store analysis results
            message.analysis["AI"] = analysis_result

            self._log.info(
                f"Successfully completed AI analysis for test: {message.full_name}"
                f"({message.id_})"
            )

        except Exception as e:
            self._log.error(
                f"AI analysis failed for test {message.full_name}({message.id_}: {e}"
            )

    def _modify_message(self, message: MessageBase) -> None:
        """
        Hook implementation for processing test result updates.

        This hook is invoked when test result messages are being processed,
        allowing the LogAgent to perform immediate analysis of failures
        before the results are propagated to other notifiers.

        Args:
            message: Test result message that may require analysis.
        """
        if (
            isinstance(message, TestResultMessage)
            and message.status == TestStatus.FAILED
        ):
            self._analyze_test_failure(message)
