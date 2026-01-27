# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os

# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages

# Default chat model options used by AI agents.
AGENT_TEMPERATURE = 0.1
AGENT_TOP_P = 0.6
AGENT_MAX_TOKENS = 8000


def get_current_directory() -> str:
    """Get the working directory for the log analyzer."""
    return os.path.dirname(os.path.realpath(__file__))
