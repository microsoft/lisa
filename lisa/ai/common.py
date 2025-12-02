# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from agent_framework import ChatOptions


# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages


def create_agent_chat_options() -> ChatOptions:
    """
    Build default ChatOptions for MAF chat agents.
    - Low temperature for consistent analysis
    - Balanced top_p for nuanced interpretation
    - Large max_output_tokens for comprehensive responses
    """
    return ChatOptions(
        temperature=0.1,
        top_p=0.6,
        max_output_tokens=8000
    )

def get_current_directory() -> str:
    """Get the working directory for the log analyzer."""
    return os.path.dirname(os.path.realpath(__file__))
