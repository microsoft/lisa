# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os

from semantic_kernel.connectors.ai.function_choice_behavior import (
    FunctionChoiceBehavior,
)
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings

# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages


def create_agent_execution_settings() -> AzureChatPromptExecutionSettings:
    """Build default execution settings for chat agents with tool calling enabled."""
    settings = AzureChatPromptExecutionSettings()
    settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
    settings.temperature = 0.1  # Low randomness for consistent analysis
    settings.top_p = 0.6  # Balanced focus for nuanced interpretation
    settings.max_tokens = 8000  # Comprehensive analysis responses

    return settings


def get_current_directory() -> str:
    """Get the working directory for the log analyzer."""
    return os.path.dirname(os.path.realpath(__file__))
