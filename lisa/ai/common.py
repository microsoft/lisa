# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from typing import Any, Awaitable, Callable, Dict, Optional

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages

# Default chat model options used by AI agents.
AGENT_TEMPERATURE = 0.1
AGENT_TOP_P = 0.6
AGENT_MAX_TOKENS = 8000

AZURE_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
AzureOpenAITokenProvider = Callable[[], Awaitable[str]]


class AzureOpenAIAuthentication:
    """Select key or Microsoft Entra ID authentication for Azure OpenAI."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key if api_key.strip() else None
        self.credential: Optional[DefaultAzureCredential] = None
        self.token_provider: Optional[AzureOpenAITokenProvider] = None

        if self.api_key is None:
            self.credential = DefaultAzureCredential()
            self.token_provider = get_bearer_token_provider(
                self.credential, AZURE_COGNITIVE_SERVICES_SCOPE
            )

    def chat_client_kwargs(self) -> Dict[str, Any]:
        if self.api_key is not None:
            return {"api_key": self.api_key}
        if self.token_provider is None:
            raise RuntimeError("Azure OpenAI token provider is not configured")
        return {"ad_token_provider": self.token_provider}

    def openai_client_kwargs(self) -> Dict[str, Any]:
        if self.api_key is not None:
            return {"api_key": self.api_key}
        if self.token_provider is None:
            raise RuntimeError("Azure OpenAI token provider is not configured")
        return {"azure_ad_token_provider": self.token_provider}

    async def close(self) -> None:
        if self.credential is not None:
            await self.credential.close()
            self.credential = None

    async def __aenter__(self) -> "AzureOpenAIAuthentication":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


def get_current_directory() -> str:
    """Get the working directory for the log analyzer."""
    return os.path.dirname(os.path.realpath(__file__))
