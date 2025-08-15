# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import argparse
import asyncio
import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Union,
)

from dotenv import load_dotenv  # type: ignore
from semantic_kernel import Kernel  # type: ignore
from semantic_kernel.agents import (  # type: ignore
    ChatCompletionAgent,
    MagenticOrchestration,
    StandardMagenticManager,
)
from semantic_kernel.agents.agent import AgentResponseItem, AgentThread  # type: ignore
from semantic_kernel.agents.runtime import InProcessRuntime  # type: ignore
from semantic_kernel.connectors.ai.azure_ai_inference import (  # type: ignore
    AzureAIInferenceTextEmbedding,
)
from semantic_kernel.connectors.ai.chat_completion_client_base import (  # type: ignore
    ChatCompletionClientBase,
)
from semantic_kernel.connectors.ai.function_choice_behavior import (  # type: ignore
    FunctionChoiceBehavior,
)
from semantic_kernel.connectors.ai.open_ai import (  # type: ignore
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents import AuthorRole, ChatMessageContent  # type: ignore
from semantic_kernel.functions import KernelArguments, kernel_function  # type: ignore
from semantic_kernel.utils.logging import setup_logging  # type: ignore

# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages


@dataclass
class Config:
    """Configuration data class for the log analyzer."""

    current_directory: str
    azure_openai_api_key: str
    azure_openai_endpoint: str
    embedding_endpoint: str
    general_deployment_name: str
    software_deployment_name: str
    log_root_path: str
    code_path: str
    selected_flow: str


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


def load_prompt(prompt_filename: str, flow: str) -> str:
    """
    Load system prompt from the prompts directory.

    Args:
        prompt_filename: Name of the prompt file (e.g., "log_search.txt").
        flow: The flow context for the prompt (e.g., "default", "gpt-5").

    Returns:
        str: Contents of the prompt file.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """

    prompt_path = os.path.join(
        get_current_directory(), "prompts", flow, prompt_filename
    )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"System prompt file not found: {prompt_path}")


def load_test_data() -> List[Dict[str, str]]:
    """
    Load test data from inputs.json file.

    Returns:
        list: List of test data

    Raises:
        FileNotFoundError: If inputs.json file is not found
        IndexError: If index is out of range
        ValueError: If JSON format is invalid
    """
    json_path = os.path.join(
        get_current_directory(), "data", "small_v20250603", "inputs.json"
    )

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            test_data = json.load(f)

        if not isinstance(test_data, list):
            raise ValueError("JSON file should contain an array of test cases")

        logging.debug(f"test data count: {len(test_data)}")
        return test_data

    except FileNotFoundError:
        raise FileNotFoundError(f"inputs.json file not found at {json_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in inputs.json: {e}")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector lengths must be the same")
    # Dot product
    dot = sum(x * y for x, y in zip(a, b))
    # Norm
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        raise ValueError("Vector norm cannot be zero")
    return dot / (norm_a * norm_b)


async def calculate_similarity_async(
    text1: str, text2: str, endpoint: str, api_key: str
) -> float:
    """
    Calculate cosine similarity between two texts using AzureAIInferenceTextEmbedding.

    Args:
        text1: First text string.
        text2: Second text string.
        endpoint: Azure OpenAI endpoint.
        api_key: Azure OpenAI API key.
    """
    kernel = Kernel()
    # Pass all recommended parameters: endpoint, api_key, deployment_name

    deployment_name = "text-embedding-3-large"

    embed = AzureAIInferenceTextEmbedding(
        endpoint=endpoint, api_key=api_key, ai_model_id=deployment_name
    )
    kernel.add_service(embed)

    texts = [text1, text2]

    try:
        resp = await embed.generate_embeddings(texts=texts)

        # Output
        for idx, text in enumerate(texts):
            logging.debug(f"Text {idx}: text length = {len(text)}")
        # Calculate cosine similarity
        similarity = cosine_similarity(resp[0], resp[1])
        logging.info(f"Cosine similarity: {similarity}")

        return similarity
    finally:
        await embed.client.close()


def calculate_similarity(text1: str, text2: str, endpoint: str, api_key: str) -> float:
    """
    Calculate cosine similarity between two texts using AzureAIInferenceTextEmbedding.
    Synchronous wrapper around async implementation.

    Args:
        text1: First text string.
        text2: Second text string.
        endpoint: Azure OpenAI endpoint.
        api_key: Azure OpenAI API key.
    """
    return asyncio.run(calculate_similarity_async(text1, text2, endpoint, api_key))


class VerbosityFilter(logging.Filter):
    """
    A filter to truncate verbose log messages rather than excluding them entirely.
    Specifically designed for OpenAI API logs to show request/response structure
    without the full content payload.
    """

    def __init__(self) -> None:
        super().__init__()
        # Patterns that indicate verbose messages we want to truncate
        self.verbose_patterns = {
            "Request options:": 200,  # Truncate after 200 chars
            "Response body:": 300,  # Truncate after 300 chars
            '"content": "': 100,  # Truncate content fields
            '"messages": [': 150,  # Truncate message arrays
            '"input": "': 100,  # Truncate input fields
            '"function_call": {': 150,  # Truncate function calls
            '"choices": [': 200,  # Truncate choices array
        }

    def filter(self, record: logging.LogRecord) -> bool:
        # Skip truncation for non-openai/http messages
        if not (
            record.name.startswith("openai")
            or record.name.startswith("httpx")
            or record.name.startswith("httpcore")
            or record.name.startswith("asyncio")
        ):
            return True

        # Only process debug level messages from these sources
        if record.levelno <= logging.DEBUG:
            message = record.getMessage()

            # Check if message is very long (exceeds threshold)
            if len(message) > VERBOSITY_LENGTH_THRESHOLD:
                # Check for patterns that should be truncated
                for pattern, max_length in self.verbose_patterns.items():
                    if pattern in message:
                        # Find the pattern position
                        pattern_pos = message.find(pattern)
                        # Keep the header and some context, then add truncation notice
                        truncated_msg = (
                            f"{message[:pattern_pos + max_length]}"
                            f"... [truncated "
                            f"{len(message) - pattern_pos - max_length} chars]"
                        )
                        record.msg = truncated_msg
                        record.args = ()
                        break
                else:
                    # If no pattern found but message is too long, truncate generically
                    if len(message) > VERBOSITY_LENGTH_THRESHOLD:
                        record.msg = (
                            f"{message[:VERBOSITY_LENGTH_THRESHOLD]}"
                            f"... [truncated "
                            f"{len(message) - VERBOSITY_LENGTH_THRESHOLD} chars]"
                        )
                        record.args = ()

        logging.debug("verbosity filter applied")

        return True


class ConsoleFilter(logging.Filter):
    """
    A filter to only allow WARN level and above for in_process_runtime logs on console.
    Other loggers will continue to use INFO level.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # For in_process_runtime logs, only allow WARN and above
        if (
            record.name.startswith("in_process_runtime")
            or record.name.startswith(
                "semantic_kernel.connectors.ai.open_ai.services.open_ai_handler"
            )
            or record.name.startswith("semantic_kernel.functions.kernel_function")
        ):
            if record.levelno < logging.WARNING:
                record.levelno = logging.DEBUG

        return True


def setup_debug_logging() -> str:
    """
    Set up debug logging for all Semantic Kernel operations to a timestamped file.
    Also sets up console logging for INFO level messages.
    This will capture all agent communications, function calls, and LLM interactions.
    """
    debug_dir = os.path.join(get_current_directory(), "logs")
    os.makedirs(debug_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tracing_filepath = os.path.join(debug_dir, f"debug_{timestamp}.log")

    # Initialize semantic kernel logging
    setup_logging()
    logging.getLogger().setLevel(logging.DEBUG)

    # Create file handler for DEBUG level
    file_handler = logging.FileHandler(tracing_filepath, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)

    # Create console handler for INFO level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Apply custom filter to console handler for in_process_runtime logs
    console_filter = ConsoleFilter()
    console_handler.addFilter(console_filter)

    # Remove any existing handlers
    for handler in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(handler)

    # Add both handlers
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().addHandler(console_handler)

    # Apply verbosity filter to prevent excessive output (only to file handler)
    verbosity_filter = VerbosityFilter()
    file_handler.addFilter(verbosity_filter)

    # Set specific log levels for noisy loggers
    logging.getLogger("semantic_kernel.functions.kernel_function_decorator").setLevel(
        logging.ERROR
    )
    logging.getLogger("in_process_runtime").setLevel(logging.WARNING)
    logging.getLogger("semantic_kernel.contents.streaming_content_mixin").setLevel(
        logging.WARNING
    )
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
        logging.WARNING
    )
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    logging.info(f"Debug logging configured. Writing to: {tracing_filepath}")
    logging.info("Console logging enabled for INFO level messages")

    return tracing_filepath


def agent_response_callback(
    message: Union[ChatMessageContent, List[ChatMessageContent]]
) -> None:
    """
    Async callback function that logs each agent's response as the
    orchestration progresses.
    Supports both ChatMessageContent and list[ChatMessageContent].
    """
    if isinstance(message, list):
        for msg in message:
            agent_response_callback(msg)
        return

    if not message.content:
        # Check if this is a function call
        if hasattr(message, "items") and message.items:
            pass
        else:
            logging.info(f"💭 {message.name} is thinking...")
    else:
        log_message = f"🤖 {message.name}: {message.content.strip()}"

        # Check for any function calls in the message
        if hasattr(message, "items") and message.items:
            for item in message.items:
                if hasattr(item, "function_name"):
                    log_message += f". Also calling: {item.function_name}"

        logging.info(log_message)


class FileSearchPlugin:
    def __init__(self, paths: List[str]) -> None:
        self._paths = paths

    @kernel_function(  # type: ignore[misc]
        name="search_files",
    )
    def search_files(
        self, search_string: str, path: str, file_extensions: str
    ) -> Dict[str, Any]:
        """
        Searches for a specific string in both standard log files and
        serial console logs.

        Args:
            search_string: The string to search for
            path: The path to the log directory to search in
            file_extensions: Required file extension filter. Can be a single extension
                          (e.g., '.log') or multiple comma-separated extensions
                          (e.g., '.log,.txt,.out').

        Returns:
            Dictionary containing structured results with file paths and line numbers
        """

        path = os.path.normpath(path)
        search_string = search_string.lower()

        if not os.path.exists(path):
            error_message = f"Log folder path does not exist: {path}"
            logging.error(error_message)
            return {"error": error_message}

        valid_result = self._valid_path(path)
        if valid_result:
            return valid_result

        # Combined results
        log_context: Dict[str, List[Dict[str, Union[str, int]]]] = {"context": []}

        files_found = 0

        # Parse comma-separated extensions and normalize to lowercase
        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        allowed_extensions = extensions

        # Search both standard logs and serial logs
        for root, _, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)

                # Skip files that in . started path, like .nox, .vscode.
                if os.path.relpath(file_path, path).startswith("."):
                    continue

                # Apply file extension filter
                _, file_ext = os.path.splitext(file_path.lower())
                if file_ext not in allowed_extensions:
                    continue

                files_found += 1

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f):
                            line_content = line.strip().lower()

                            if search_string in line_content:
                                parsed_line: Dict[str, Union[str, int]] = {}
                                # Ensure we use the absolute, normalized path
                                parsed_line["file_path"] = os.path.abspath(file_path)
                                parsed_line["match_line_number"] = i
                                parsed_line["matched_text"] = line_content

                                log_context["context"].append(parsed_line)

                except Exception as e:
                    logging.error(f"Error processing file {file_path}: {str(e)}")
                    continue

        match_count = len(log_context["context"])
        logging.info(
            f"Search results: {files_found} files processed, "
            f"{match_count} matches found."
        )

        return log_context

    @kernel_function(  # type: ignore[misc]
        name="read_text_file",
    )
    def read_text_file(
        self, start_line_offset: int, file_path: str, line_count: int
    ) -> Dict[str, str]:
        """
        Extracts lines from a file starting from a specific line number.

        Args:
            start_line_offset: The line number to start reading from (1-based)
            file_path: The path to the file to read
            line_count: Number of lines to read

        Returns:
            Dictionary containing either file content or error information
        """

        traceback: List[str] = []
        norm_path = os.path.normpath(file_path)

        # Validate the file path
        valid_result = self._valid_path(file_path)
        if valid_result:
            return valid_result

        # Add debugging for path resolution
        logging.debug(f"read_text_file called with file_path: {file_path}")
        logging.debug(f"read_text_file normalized path: {norm_path}")
        logging.debug(f"read_text_file absolute path: {os.path.abspath(norm_path)}")
        logging.debug(f"Path exists check: {os.path.exists(norm_path)}")

        if not os.path.exists(norm_path):
            error_message = f"File not found: {norm_path}"
            logging.error(error_message)

            # Add additional debugging to help identify the issue
            parent_dir = os.path.dirname(norm_path)
            logging.error(f"Parent directory: {parent_dir}")
            logging.error(f"Parent directory exists: {os.path.exists(parent_dir)}")

            if os.path.exists(parent_dir):
                try:
                    files_in_parent = os.listdir(parent_dir)
                    logging.error(f"Files in parent directory: {files_in_parent}")
                except Exception as e:
                    logging.error(f"Cannot list parent directory: {e}")

            return {"error": error_message}

        traceback_start = max(1, start_line_offset)
        traceback_end = traceback_start + line_count - 1

        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, start=1):
                    if traceback_start <= i <= traceback_end:
                        traceback.append(f"({i}): {line.rstrip()}")
                    if i > traceback_end:
                        break

            logging.info(
                f"Successfully extracted {len(traceback)} lines of context",
            )
        except Exception as e:
            error_message = f"Error reading file {norm_path}: {str(e)}"
            logging.error(error_message)
            return {"error": error_message}

        result = "\n".join(traceback)
        logging.debug(f"read_text_file result: {result}")
        return {"content": result}

    def _validate_list_files_input(
        self, folder_path: str, offset: int
    ) -> Optional[Dict[str, Any]]:
        valid_result = self._valid_path(folder_path)
        if valid_result:
            return valid_result

        norm_file_path = os.path.normpath(folder_path)

        if not os.path.exists(norm_file_path):
            error_message = f"Directory path does not exist: {norm_file_path}"
            logging.error(error_message)
            return {"error": error_message}

        if not os.path.isdir(norm_file_path):
            error_message = f"Path is not a directory: {norm_file_path}"
            logging.error(error_message)
            return {"error": error_message}

        if offset < 0:
            error_message = f"Invalid offset: {offset}. Offset must be non-negative."
            logging.error(error_message)
            return {"error": error_message}

        return None

    def _parse_file_extensions(self, file_extensions: str) -> List[str]:
        return [ext.strip().lower() for ext in file_extensions.split(",")]

    def _matches_extension(self, file_path: str, allowed_extensions: List[str]) -> bool:
        _, file_ext = os.path.splitext(file_path.lower())
        return file_ext in allowed_extensions

    def _find_files_recursive(
        self,
        folder_path: str,
        allowed_extensions: List[str],
    ) -> List[str]:
        files = []

        for root, _, filenames in os.walk(folder_path):
            for filename in filenames:
                full_path = os.path.join(root, filename)

                # Skip hidden files and directories like .nox, .vscode
                if os.path.relpath(full_path, folder_path).startswith("."):
                    continue

                if self._matches_extension(full_path, allowed_extensions):
                    files.append(full_path)
        return files

    def _find_files_immediate(
        self, folder_path: str, allowed_extensions: List[str]
    ) -> List[str]:
        files = []

        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isfile(item_path) and self._matches_extension(
                    item_path, allowed_extensions
                ):
                    files.append(item_path)
        except PermissionError:
            error_message = f"Permission denied accessing directory: {folder_path}"
            logging.error(error_message)
            raise PermissionError(error_message)
        return files

    def _discover_files(
        self, folder_path: str, file_extensions: str, is_recursive: bool
    ) -> List[str]:
        norm_file_path = os.path.normpath(folder_path)
        allowed_extensions = self._parse_file_extensions(file_extensions)

        if is_recursive:
            return self._find_files_recursive(norm_file_path, allowed_extensions)
        else:
            return self._find_files_immediate(norm_file_path, allowed_extensions)

    def _paginate_files(
        self,
        files: List[str],
        offset: int,
        max_files: int,
        file_extensions: str,
        folder_path: str,
    ) -> Dict[str, Any]:
        total_files = len(files)

        # Validate offset against total files
        if offset >= total_files and total_files > 0:
            error_message = f"Offset {offset} is beyond total file count {total_files}"
            logging.error(error_message)
            return {"error": error_message}

        # Calculate pagination boundaries
        start = offset
        end = min(offset + max_files, total_files)
        paginated_files = files[start:end]

        # Calculate pagination metadata
        has_more_files = end < total_files
        next_offset = end if has_more_files else None

        # Log results
        extension_info = f" with extension '{file_extensions}'"
        logging.info(
            f"Listed {len(paginated_files)} files{extension_info} "
            f"(offset: {offset}, total: {total_files}) under {folder_path}"
        )

        logging.debug(f"list_files found: {paginated_files}")

        return {
            "files": paginated_files,
            "pagination": {
                "offset": offset,
                "max_files": max_files,
                "total_files": total_files,
                "returned_files": len(paginated_files),
                "has_more_files": has_more_files,
                "next_offset": next_offset,
            },
        }

    @kernel_function(  # type: ignore[misc]
        name="list_files",
    )
    def list_files(
        self,
        folder_path: str,
        file_extensions: str,
        recursive: bool = True,
        max_files: int = 500,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Lists all files under a specified directory path with pagination support.

        Args:
            folder_path: The directory path to search for files
            file_extensions: Required file extension filter. Can be a single extension
                          (e.g., '.log') or multiple comma-separated extensions
                          (e.g., '.log,.txt,.out').
            recursive: If True, searches subdirectories recursively.
                      If False, only searches the immediate directory.
            max_files: Maximum number of files to return (default: 500)
            offset: Number of files to skip from the beginning (default: 0)

        Returns:
            Dictionary containing either file paths or error information,
            along with pagination metadata
        """

        logging.debug(
            f"Listing files under {folder_path} "
            f"(recursive: {recursive}, max_files: {max_files}, offset: {offset}, "
            f"file_extensions: {file_extensions})"
        )

        # Validate inputs and paths
        validation_error = self._validate_list_files_input(folder_path, offset)
        if validation_error:
            return validation_error

        # Discover files and filter files
        try:
            files = self._discover_files(folder_path, file_extensions, recursive)
            result = self._paginate_files(
                files,
                offset,
                max_files,
                file_extensions,
                folder_path,
            )
            return result
        except Exception as e:
            logging.error(f"Error occurred while listing files: {e}")
            return {"error": str(e)}

    def _valid_path(self, path: str) -> Dict[str, str]:
        """
        Validate if the provided path is under the allowed paths.
        This ensures that the agent only operates within the specified directories.
        Args:
            path: The file path to validate.
        Returns:
            bool: True if the path is valid, False otherwise.
        """
        norm_path = os.path.normpath(path)
        for allowed_path in self._paths:
            if norm_path.startswith(os.path.normpath(allowed_path)):
                return {}
        return {"error": f"Path is out of allowed directories: {path}"}


class FileSearchAgentBase(ChatCompletionAgent):  # type: ignore
    """
    Custom agent base class for LISA file search agents.

    Provides consistent message handling, AI service setup, and conversation management
    for all file search agents (LogSearchAgent, CodeSearchAgent, etc.).

    Features:
    - Automatic message normalization (strings -> ChatMessageContent)
    - Azure OpenAI and OpenAI service support
    - Context preservation and filtering
    - Streaming response handling
    - Additional context injection capabilities
    """

    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        paths: List[str],
        deployment_name: str,
        api_key: str,
        base_url: str,
    ) -> None:
        super().__init__(
            service=self._create_ai_service(deployment_name, api_key, base_url),
            name=name,
            description=description,
            instructions=instructions,
            plugins=[FileSearchPlugin(paths=paths)],
        )

    def _create_ai_service(
        self,
        deployment_name: str,
        api_key: str,
        base_url: str,
        instruction_role: Literal["system", "developer"] = "system",
    ) -> ChatCompletionClientBase:
        """Create an AI service for the file search agent using AzureAIInference.

        Args:
            deployment_name: The model deployment name for Azure AI Inference
            api_key: The API key for Azure AI Inference
            base_url: The endpoint URL for Azure AI Inference
            instruction_role: Unused parameter, kept for compatibility

        Returns:
            ChatCompletionClientBase: The configured AI service instance.
        """

        return AzureChatCompletion(
            deployment_name=deployment_name,
            api_key=api_key,
            endpoint=base_url,
            api_version="2024-12-01-preview",
        )

    # Execution settings are provided by the module-level helper

    async def invoke_with_context(
        self,
        *,
        messages: Optional[
            Union[str, ChatMessageContent, List[Union[str, ChatMessageContent]]]
        ] = None,
        thread: Optional[AgentThread] = None,
        on_intermediate_message: Optional[
            Callable[[ChatMessageContent], Awaitable[None]]
        ] = None,
        arguments: Optional[KernelArguments] = None,
        kernel: Optional[Kernel] = None,
        additional_context: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterable[AgentResponseItem[ChatMessageContent]]:
        """
        Invoke the log analyzer agent with enhanced context handling.

        This method extends the base invoke functionality with log analyzer-specific
        features like automatic context injection and path information.

        Args:
            messages: The input messages (string, ChatMessageContent, or either).
            thread: Optional agent thread for conversation management.
            on_intermediate_message: Callback for intermediate message handling.
            arguments: Kernel arguments for function execution.
            kernel: Kernel instance for function execution.
            additional_context: Extra context to inject into the conversation.
            **kwargs: Additional arguments passed to the base invoke method.

        Yields:
            AgentResponseItem[ChatMessageContent]: Streaming responses from the agent.
        """
        # Normalize input messages to consistent format
        normalized_messages = self._normalize_messages(messages)

        # Inject log analyzer-specific context
        context_parts = []

        if additional_context:
            context_parts.append(f"Additional context: {additional_context}")

        if context_parts:
            context_message = "Available resources and context:\n" + "\n".join(
                context_parts
            )
            normalized_messages.append(
                ChatMessageContent(role=AuthorRole.USER, content=context_message)
            )

        # Filter out empty or function-only messages to avoid polluting context
        # This is crucial for log analysis where function call results can be verbose
        messages_to_pass = [
            m for m in normalized_messages if m.content and m.content.strip()
        ]

        # Call the underlying ChatCompletionAgent with cleaned messages
        async for response in super().invoke(
            messages=messages_to_pass,
            thread=thread,
            on_intermediate_message=on_intermediate_message,
            arguments=arguments,
            kernel=kernel,
            execution_settings=create_agent_execution_settings(),
            **kwargs,
        ):
            yield response

    async def invoke_simple(self, prompt: str) -> str:
        """
        Simplified invoke method that returns just the content string.

        This is a convenience method for simple use cases where you just want
        the AI's response as a string without dealing with streaming or complex types.

        Args:
            prompt: Simple string prompt to send to the agent.

        Returns:
            str: The agent's response content, or a default message if no response.
        """
        async for response in self.invoke(messages=prompt):
            if response.content and response.content.content:
                return str(response.content.content)
        return "No response generated"

    def _normalize_messages(
        self,
        messages: Optional[
            Union[str, ChatMessageContent, List[Union[str, ChatMessageContent]]]
        ],
    ) -> List[ChatMessageContent]:
        """
        Normalize various message input formats to a
        consistent list of ChatMessageContent.

        This method handles the complexity of different input formats
        that might be passed to log analyzer agents, ensuring consistent
        processing regardless of input type.

        Args:
            messages: Input messages in various formats
            (None, string, ChatMessageContent, or lists).

        Returns:
            list[ChatMessageContent]: Normalized list of ChatMessageContent objects.
        """
        if messages is None:
            return []

        if isinstance(messages, (str, ChatMessageContent)):
            messages = [messages]

        normalized: List[ChatMessageContent] = []

        for msg in messages:
            if isinstance(msg, str):
                # Convert strings to USER role messages
                normalized.append(ChatMessageContent(role=AuthorRole.USER, content=msg))
            else:
                # Preserve existing ChatMessageContent as-is
                normalized.append(msg)

        return normalized


class LogSearchAgent(FileSearchAgentBase):
    """
    Specialized agent for searching and analyzing log files.

    This agent focuses on:
    - LISA log format parsing and analysis
    - Error pattern detection in standard and serial console logs
    - Fuzzy matching for error message identification
    - Timeline reconstruction and context extraction
    """

    def __init__(
        self, log_paths: List[str], deployment_name: str, api_key: str, base_url: str
    ) -> None:
        # Load specialized system prompt for log search
        instructions = load_prompt("log_search.txt", flow="default")

        # Initialize with Azure OpenAI service and log analysis plugin
        super().__init__(
            name="LogSearchAgent",
            description=(
                "Searches and analyzes log files for error patterns "
                "and diagnostic information."
            ),
            instructions=instructions,
            paths=log_paths,
            deployment_name=deployment_name,
            api_key=api_key,
            base_url=base_url,
        )


class CodeSearchAgent(FileSearchAgentBase):
    """
    Specialized agent for examining source code and implementations.

    This agent focuses on:
    - Source code analysis related to log errors
    - Traceback parsing and file mapping
    - Implementation logic understanding
    - Code-to-error correlation analysis
    """

    def __init__(
        self, code_paths: List[str], deployment_name: str, api_key: str, base_url: str
    ) -> None:
        # Load specialized system prompt for code search
        instructions = load_prompt("code_search.txt", flow="default")

        # Initialize with Azure OpenAI service and log analysis plugin
        super().__init__(
            name="CodeSearchAgent",
            description=(
                "Examines source code files and analyzes implementations "
                "related to errors."
            ),
            instructions=instructions,
            paths=code_paths,
            deployment_name=deployment_name,
            api_key=api_key,
            base_url=base_url,
        )


def _load_config(selected_flow: str) -> Config:
    """
    Load environment variables and validate required configs.
    """
    current_directory = get_current_directory()
    load_dotenv(os.path.join(current_directory, ".env"))

    # Get environment variables
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    embedding_endpoint = os.getenv("EMBEDDING_ENDPOINT")
    general_deployment_name = os.getenv("GENERAL_DEPLOYMENT_NAME")
    software_deployment_name = os.getenv("SOFTWARE_DEPLOYMENT_NAME")
    log_root_path = os.getenv("LOG_ROOT_PATH")
    code_path = os.getenv("CODE_PATH")

    return Config(
        current_directory=current_directory,
        azure_openai_api_key=azure_openai_api_key,  # type: ignore
        azure_openai_endpoint=azure_openai_endpoint,  # type: ignore
        embedding_endpoint=embedding_endpoint,  # type: ignore
        general_deployment_name=general_deployment_name,  # type: ignore
        software_deployment_name=software_deployment_name,  # type: ignore
        log_root_path=log_root_path,  # type: ignore
        code_path=code_path,  # type: ignore
        selected_flow=selected_flow,
    )


def _prepare_test_data(args: argparse.Namespace) -> List[Dict[str, str]]:
    """
    Load and filter test data based on command line arguments.
    """
    test_data = load_test_data()

    if args.command == "single":
        if not (0 <= args.test_index < len(test_data)):
            raise ValueError(
                f"Test index {args.test_index} is out of range. "
                f"Valid range is 0 to {len(test_data) - 1}."
            )
        return [test_data[args.test_index]]

    return test_data


def _clean_json_markers(text: str) -> str:
    """
    Remove JSON code block markers from text.
    """
    text = text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def _extract_generated_content(generated_text: Any) -> Any:
    if isinstance(generated_text, list):
        generated_text = " ".join(
            msg if isinstance(msg, str) else str(getattr(msg, "content", msg))
            for msg in generated_text
        )
    elif hasattr(generated_text, "content"):
        generated_text = str(getattr(generated_text, "content", generated_text))
    else:
        generated_text = str(generated_text)

    # Clean JSON markers
    generated_text = _clean_json_markers(generated_text)

    return json.loads(generated_text)


def _get_keywords(ground_truth: Union[Dict[str, List[str]], List[str], str]) -> str:
    """Extract keywords from ground truth data."""
    if isinstance(ground_truth, dict):
        keywords: List[str] = ground_truth.get("problem_keywords", [""])
    elif isinstance(ground_truth, list):
        keywords = ground_truth
    else:
        # ground_truth is a string
        keywords = [ground_truth]

    if isinstance(keywords, list):
        keywords_str = ", ".join(keywords)

    return keywords_str


def _process_single_test_case(item: Dict[str, Any], config: Config) -> Dict[str, Any]:
    """
    Process a single test case and gather results.
    """
    log_folder_path = os.path.join(config.log_root_path, item["path"])
    error_message = item["error_message"]

    generated_text = analyze(
        config.current_directory,
        config.azure_openai_api_key,
        config.azure_openai_endpoint,
        config.general_deployment_name,
        config.software_deployment_name,
        config.code_path,
        log_folder_path,
        error_message,
        selected_flow=config.selected_flow,
    )

    # Extract keywords
    generated_keywords = _get_keywords(_extract_generated_content(generated_text))
    ground_truth_keywords = _get_keywords(item["ground_truth"])

    logging.info(f"Generated keywords: {generated_keywords}")
    logging.info(f"Ground truth keywords: {ground_truth_keywords}")

    # Calculate similarity
    similarity = calculate_similarity(
        generated_keywords,
        ground_truth_keywords,
        config.embedding_endpoint,
        config.azure_openai_api_key,
    )

    return {
        "similarity": similarity,
        "generated_keywords": generated_keywords,
        "ground_truth_keywords": ground_truth_keywords,
    }


def _process_test_cases(
    test_data: List[Dict[str, Any]], config: Config
) -> Dict[str, Any]:
    """
    Process all test cases and gather results.
    """
    results: Dict[str, List[Any]] = {
        "similarities": [],
        "generated_keywords_list": [],
        "ground_truth_keywords_list": [],
        "test_ids": [],
    }

    for item in test_data:
        logging.info(f"Analyzing test case {item['id']}: {item['path']}")

        # Process single test test case
        test_result = _process_single_test_case(item, config)

        results["similarities"].append(test_result["similarity"])
        results["generated_keywords_list"].append(test_result["generated_keywords"])
        results["ground_truth_keywords_list"].append(
            test_result["ground_truth_keywords"]
        )
        results["test_ids"].append(item["id"])

    return results


def _output_detailed_results(results: Dict[str, Any]) -> None:
    """
    Output detailed results for each test case.
    """
    logging.info("=== DETAILED RESULTS ===")

    test_ids: List[Any] = results["test_ids"]
    similarities: List[Any] = results["similarities"]
    gen_list: List[Any] = results["generated_keywords_list"]
    gt_list: List[Any] = results["ground_truth_keywords_list"]

    for index in range(
        min(len(test_ids), len(similarities), len(gen_list), len(gt_list))
    ):
        test_id = test_ids[index]
        similarity = similarities[index]
        generated = gen_list[index]
        ground_truth = gt_list[index]
        logging.info(f"Test case {index} (ID: {test_id}): ")
        logging.info(f"  Similarity: {similarity: .6f}")
        logging.info(f"  Generated keywords: {generated}")
        logging.info(f"  Ground truth keywords: {ground_truth}")
        logging.info("")


def _output_summary_statistics(results: Dict[str, Any], config: Config) -> None:
    """
    Output summary statistics for all test cases.
    """
    similarities = results["similarities"]

    logging.info("=== SUMMARY ===")

    # Individual similarities
    for index, similarity in enumerate(similarities):
        logging.info(f"Test case {index} Similarity: {similarity: .6f}")

    logging.info(
        f"General deployment name: {config.general_deployment_name}, "
        f"Software deployment name: {config.software_deployment_name}"
    )

    # Aggregate statistics
    avg_similarity = sum(similarities) / len(similarities)
    logging.info(
        f"Average similarity: {avg_similarity: .6f}, "
        f"Best: {max(similarities): .6f}, "
        f"Worst: {min(similarities):.6f}, "
        f"Total test cases: {len(similarities)}"
    )


def _output_results(results: Dict[str, Any], config: Config) -> None:
    """
    Output detailed results and summary statistics.
    """
    if not results["similarities"]:
        logging.info("No results to display.")
        return

    _output_detailed_results(results)
    _output_summary_statistics(results, config)


def main() -> None:
    """
    Main function that orchestrates a simple multi-agent log analysis workflow.

    Uses specialized agents to analyze LISA test errors by combining log analysis
    and code inspection capabilities.
    """

    # Setup and validation
    args = parse_args()
    config = _load_config(args.flow)
    setup_debug_logging()

    # Load and filter test data
    test_data = _prepare_test_data(args)

    # Process test cases
    results = _process_test_cases(test_data, config)

    _output_results(results, config)


def parse_args() -> argparse.Namespace:
    """
    Set up and parse command line arguments for the log analyzer agent.
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(description="AI Log Analyzer Agent")
    subparsers = parser.add_subparsers(dest="command")

    # 'eval' subcommand (default)
    subparsers.add_parser("eval", help="Run evaluation on all test cases (default)")

    # 'single' subcommand
    single_parser = subparsers.add_parser(
        "single", help="Run single test case analysis"
    )
    single_parser.add_argument(
        "-t",
        "--test-index",
        type=int,
        default=8,
        help="Index of the test case to analyze (default: 8, ranging 0-11)",
    )

    # Global options
    parser.add_argument(
        "--flow",
        choices=["default", "gpt-5"],
        default="default",
        help=(
            "Select the analysis flow to use. Choices: 'default', 'gpt-5'. "
            "(default: 'default')"
        ),
    )

    parser.set_defaults(command="eval")

    return parser.parse_args()


async def _async_analyze_default(
    current_directory: str,
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: str,
    error_message: str,
) -> str:
    """
    Default async analysis method using multi-agent orchestration.
    """
    system_instructions = load_prompt("user.txt", flow="default")

    # Include the actual error message in the analysis prompt
    analysis_prompt = f"""{system_instructions}
**ERROR MESSAGE TO ANALYZE: **
{error_message}
**AVAILABLE LOG PATHS: **
{log_folder_path}
**AVAILABLE CODE PATHS: **
{code_path}
    """

    # Create specialized agents using the custom base class
    logging.info("Initializing agents")

    log_search_agent = LogSearchAgent(
        log_paths=[log_folder_path],
        deployment_name=software_deployment_name,
        api_key=azure_openai_api_key,
        base_url=azure_openai_endpoint,
    )
    code_search_agent = CodeSearchAgent(
        code_paths=[code_path],
        deployment_name=software_deployment_name,
        api_key=azure_openai_api_key,
        base_url=azure_openai_endpoint,
    )

    agents = [log_search_agent, code_search_agent]

    logging.info("Setting up Magentic orchestration")

    # Create magentic orchestration
    chat_completion_service = AzureChatCompletion(
        deployment_name=general_deployment_name,
        api_key=azure_openai_api_key,
        endpoint=azure_openai_endpoint,
        api_version="2024-12-01-preview",
    )

    # Load the final answer prompt
    final_answer_prompt = load_prompt("final_answer.txt", flow="default")

    # Create execution settings for the manager using the shared builder
    manager_execution_settings = create_agent_execution_settings()

    manager = StandardMagenticManager(
        chat_completion_service=chat_completion_service,
        final_answer_prompt=final_answer_prompt,
        execution_settings=manager_execution_settings,
    )

    magentic_orchestration = MagenticOrchestration(
        members=agents,
        manager=manager,
        agent_response_callback=agent_response_callback,
    )

    runtime = InProcessRuntime()
    runtime.start()

    logging.info(f"Starting analysis for: {error_message[:100]}...")

    try:
        # Execute analysis with timeout protection and retry logic
        async def run_analysis() -> Any:
            orchestration_result = await magentic_orchestration.invoke(
                task=analysis_prompt,
                runtime=runtime,
            )
            return await orchestration_result.get()

        # Retry configuration
        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                # Set a reasonable timeout (5 minutes) with retry
                value: Any = await asyncio.wait_for(run_analysis(), timeout=300.0)

                # if the result is not the last message, the format is not
                # correct. It will raise an exception, and trigger retry.
                if isinstance(value, list):
                    value = " ".join(
                        (
                            msg.content.strip()
                            if hasattr(msg, "content") and msg.content
                            else ""
                        )
                        for msg in value
                    )
                elif hasattr(value, "content"):
                    value = value.content.strip()
                else:
                    value = str(value).strip()

                break

            except Exception as e:
                if attempt == max_retries:
                    # Last attempt failed, re-raise the exception
                    logging.error(
                        f"Analysis failed after {max_retries + 1} attempts: {e}"
                    )
                    raise

                # Calculate delay with exponential backoff
                logging.warning(f"Analysis attempt {attempt + 1} failed: {e}")

        logging.info("🎯 **FINAL ANALYSIS RESULT**")
        logging.info(value)
        return str(value)

    finally:
        try:
            await runtime.stop_when_idle()
            await runtime.close()
        except Exception as e:
            logging.debug(f"Error during runtime cleanup: {e}")


async def _async_analyze_gpt5(
    current_directory: str,
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: str,
    error_message: str,
) -> str:
    """
    GPT-5 specific async analysis method.
    This is a placeholder for future GPT-5 specific implementation.
    """
    # For now, use the same implementation as default
    # This can be extended with GPT-5 specific logic in the future
    logging.info("Using GPT-5 analysis flow")
    return await _async_analyze_default(
        current_directory,
        azure_openai_api_key,
        azure_openai_endpoint,
        general_deployment_name,
        software_deployment_name,
        code_path,
        log_folder_path,
        error_message,
    )


def analyze(
    current_directory: str,
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: str,
    error_message: str,
    selected_flow: str,
) -> str:
    """
    Analyze logs using async agents with asyncio.run for execution.
    Supports different analysis flows based on selected_flow parameter.
    """

    # Select the appropriate analysis method based on selected_flow
    if selected_flow == "gpt-5":
        async_analyze_func = _async_analyze_gpt5
    else:  # default flow
        async_analyze_func = _async_analyze_default

    logging.info(f"Using analysis flow: {selected_flow}")

    return asyncio.run(
        async_analyze_func(
            current_directory,
            azure_openai_api_key,
            azure_openai_endpoint,
            general_deployment_name,
            software_deployment_name,
            code_path,
            log_folder_path,
            error_message,
        )
    )


if __name__ == "__main__":
    main()
