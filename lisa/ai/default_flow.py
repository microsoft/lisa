# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import os
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

from semantic_kernel import Kernel

# pylint: disable=no-name-in-module
from semantic_kernel.agents import (
    ChatCompletionAgent,
    MagenticOrchestration,
    StandardMagenticManager,
)
from semantic_kernel.agents.agent import AgentResponseItem, AgentThread
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.connectors.ai.chat_completion_client_base import (
    ChatCompletionClientBase,
)
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent
from semantic_kernel.functions import KernelArguments, kernel_function

from lisa.ai.common import create_agent_execution_settings, get_current_directory
from lisa.util.logger import Logger

# Module-level logger for callback functions and utility methods
_logger: Logger


def _load_prompt(prompt_filename: str, flow: str) -> str:
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


def _agent_response_callback(
    message: Union[ChatMessageContent, List[ChatMessageContent]]
) -> None:
    """
    Async callback function that logs each agent's response as the
    orchestration progresses.
    Supports both ChatMessageContent and list[ChatMessageContent].
    """
    if isinstance(message, list):
        for msg in message:
            _agent_response_callback(msg)
        return

    if not message.content:
        # Check if this is a function call
        if hasattr(message, "items") and message.items:
            pass
        else:
            _logger.info(f"💭 {message.name} is thinking...")
    else:
        log_message = f"🤖 {message.name}: {message.content.strip()}"

        # Check for any function calls in the message
        if hasattr(message, "items") and message.items:
            for item in message.items:
                if hasattr(item, "function_name"):
                    log_message += f". Also calling: {item.function_name}"

        _logger.info(log_message)


class FileSearchPlugin:
    def __init__(self, paths: List[str], logger: Logger) -> None:
        self._paths = paths
        self._logger = logger

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
            self._logger.error(error_message)
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
                    self._logger.error(f"Error processing file {file_path}: {str(e)}")
                    continue

        match_count = len(log_context["context"])
        self._logger.info(
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
        self._logger.debug(f"read_text_file called with file_path: {file_path}")
        self._logger.debug(f"read_text_file normalized path: {norm_path}")
        self._logger.debug(
            f"read_text_file absolute path: {os.path.abspath(norm_path)}"
        )
        self._logger.debug(f"Path exists check: {os.path.exists(norm_path)}")

        if not os.path.exists(norm_path):
            error_message = f"File not found: {norm_path}"
            self._logger.error(error_message)

            # Add additional debugging to help identify the issue
            parent_dir = os.path.dirname(norm_path)
            self._logger.error(f"Parent directory: {parent_dir}")
            self._logger.error(f"Parent directory exists: {os.path.exists(parent_dir)}")

            if os.path.exists(parent_dir):
                try:
                    files_in_parent = os.listdir(parent_dir)
                    self._logger.error(f"Files in parent directory: {files_in_parent}")
                except Exception as e:
                    self._logger.error(f"Cannot list parent directory: {e}")

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

            self._logger.info(
                f"Successfully extracted {len(traceback)} lines of context",
            )
        except Exception as e:
            error_message = f"Error reading file {norm_path}: {str(e)}"
            self._logger.error(error_message)
            return {"error": error_message}

        result = "\n".join(traceback)
        self._logger.debug(f"read_text_file result: {result}")
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
            self._logger.error(error_message)
            return {"error": error_message}

        if not os.path.isdir(norm_file_path):
            error_message = f"Path is not a directory: {norm_file_path}"
            self._logger.error(error_message)
            return {"error": error_message}

        if offset < 0:
            error_message = f"Invalid offset: {offset}. Offset must be non-negative."
            self._logger.error(error_message)
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
            self._logger.error(error_message)
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
            self._logger.error(error_message)
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
        self._logger.info(
            f"Listed {len(paginated_files)} files{extension_info} "
            f"(offset: {offset}, total: {total_files}) under {folder_path}"
        )

        self._logger.debug(f"list_files found: {paginated_files}")

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

        self._logger.debug(
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
            self._logger.error(f"Error occurred while listing files: {e}")
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
        logger: Logger,
    ) -> None:
        super().__init__(
            service=self._create_ai_service(deployment_name, api_key, base_url),
            name=name,
            description=description,
            instructions=instructions,
            plugins=[FileSearchPlugin(paths=paths, logger=logger)],
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
        self,
        log_paths: List[str],
        deployment_name: str,
        api_key: str,
        base_url: str,
        logger: Logger,
    ) -> None:
        # Load specialized system prompt for log search
        instructions = _load_prompt("log_search.txt", flow="default")

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
            logger=logger,
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
        self,
        code_paths: List[str],
        deployment_name: str,
        api_key: str,
        base_url: str,
        logger: Logger,
    ) -> None:
        # Load specialized system prompt for code search
        instructions = _load_prompt("code_search.txt", flow="default")

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
            logger=logger,
        )


async def async_analyze_default(
    current_directory: str,
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: str,
    error_message: str,
    logger: Logger,
) -> str:
    """
    Default async analysis method using multi-agent orchestration.
    """
    system_instructions = _load_prompt("user.txt", flow="default")

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
    logger.info("Initializing agents")

    # Set global logger for callbacks
    global _logger
    _logger = logger

    log_search_agent = LogSearchAgent(
        log_paths=[log_folder_path],
        deployment_name=software_deployment_name,
        api_key=azure_openai_api_key,
        base_url=azure_openai_endpoint,
        logger=logger,
    )
    code_search_agent = CodeSearchAgent(
        code_paths=[code_path],
        deployment_name=software_deployment_name,
        api_key=azure_openai_api_key,
        base_url=azure_openai_endpoint,
        logger=logger,
    )

    agents = [log_search_agent, code_search_agent]

    logger.info("Setting up Magentic orchestration")

    # Create magentic orchestration
    chat_completion_service = AzureChatCompletion(
        deployment_name=general_deployment_name,
        api_key=azure_openai_api_key,
        endpoint=azure_openai_endpoint,
        api_version="2024-12-01-preview",
    )

    # Load the final answer prompt
    final_answer_prompt = _load_prompt("final_answer.txt", flow="default")

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
        agent_response_callback=_agent_response_callback,
    )

    runtime = InProcessRuntime()
    runtime.start()

    logger.info(f"Starting analysis for: {error_message[:100]}...")

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
                    logger.error(
                        f"Analysis failed after {max_retries + 1} attempts: {e}"
                    )
                    raise

                # Calculate delay with exponential backoff
                logger.warning(f"Analysis attempt {attempt + 1} failed: {e}")

        logger.info("🎯 **FINAL ANALYSIS RESULT**")
        logger.info(value)
        return str(value)

    finally:
        try:
            await runtime.stop_when_idle()
            await runtime.close()
        except Exception as e:
            logger.debug(f"Error during runtime cleanup: {e}")
            logger.debug(f"Error during runtime cleanup: {e}")
