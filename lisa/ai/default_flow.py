# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union, cast

# pylint: disable=no-name-in-module
from agent_framework import (
    ChatAgent,
    ChatMessage,
    ExecutorCompletedEvent,
    ExecutorInvokedEvent,
    SequentialBuilder,
    WorkflowOutputEvent,
)
from agent_framework.azure import AzureOpenAIChatClient

from . import logger
from .common import create_agent_chat_options, get_current_directory

# Define agent name constants
LOG_SEARCH_AGENT_NAME = "LogSearchAgent"
CODE_SEARCH_AGENT_NAME = "CodeSearchAgent"
SUMMARY_AGENT_NAME = "SummaryAgent"


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


class FileSearchPlugin:
    def __init__(self, paths: List[str]) -> None:
        self._paths: List[str] = []
        for path in paths:
            self._paths.append(os.path.normpath(path))

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
            logger.info(error_message)
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

        logger.info(
            f"Searching for '{search_string}' in {path} "
            f"with extensions {extensions}"
        )

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
                    logger.info(f"Error processing file {file_path}: {str(e)}")
                    continue

        match_count = len(log_context["context"])
        logger.info(
            f"Searched '{search_string}', {files_found} files processed, "
            f"{match_count} matches found."
        )

        return log_context

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
        logger.debug(f"read_text_file called with file_path: {file_path}")
        logger.debug(f"read_text_file normalized path: {norm_path}")
        logger.debug(f"read_text_file absolute path: {os.path.abspath(norm_path)}")
        logger.debug(f"Path exists check: {os.path.exists(norm_path)}")

        if not os.path.exists(norm_path):
            error_message = f"File not found: {norm_path}"
            logger.info(error_message)

            # Add additional debugging to help identify the issue
            parent_dir = os.path.dirname(norm_path)
            logger.debug(f"Parent directory: {parent_dir}")
            logger.debug(f"Parent directory exists: {os.path.exists(parent_dir)}")

            if os.path.exists(parent_dir):
                try:
                    files_in_parent = os.listdir(parent_dir)
                    logger.debug(f"Files in parent directory: {files_in_parent}")
                except Exception as e:
                    logger.debug(f"Cannot list parent directory: {e}")

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

            logger.info(
                f"Successfully extracted {len(traceback)} lines of context",
            )
        except Exception as e:
            error_message = f"Error reading file {norm_path}: {str(e)}"
            logger.info(error_message)
            return {"error": error_message}

        result = "\n".join(traceback)
        logger.debug(f"read_text_file result: {result}")
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
            logger.info(error_message)
            return {"error": error_message}

        if not os.path.isdir(norm_file_path):
            error_message = f"Path is not a directory: {norm_file_path}"
            logger.info(error_message)
            return {"error": error_message}

        if offset < 0:
            error_message = f"Invalid offset: {offset}. Offset must be non-negative."
            logger.info(error_message)
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
            logger.info(error_message)
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
            logger.info(error_message)
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
        logger.info(
            f"Listed {len(paginated_files)} files{extension_info} "
            f"(offset: {offset}, total: {total_files}) under {folder_path}"
        )

        logger.debug(f"list_files found: {paginated_files}")

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

        logger.debug(
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
            files = self._discover_files(
                folder_path=folder_path,
                file_extensions=file_extensions,
                is_recursive=recursive,
            )
            result = self._paginate_files(
                files=files,
                offset=offset,
                max_files=max_files,
                file_extensions=file_extensions,
                folder_path=folder_path,
            )
            return result
        except Exception as e:
            logger.info(f"Error occurred while listing files: {e}")
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
            if norm_path.startswith(allowed_path):
                return {}
        return {"error": f"Path is out of allowed directories: {path}"}


class FileSearchAgentBase(ChatAgent):  # type: ignore
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
        chat_client = self._create_chat_client(
            deployment_name=deployment_name,
            api_key=api_key,
            base_url=base_url,
        )
        plugin = FileSearchPlugin(paths=paths)
        tools = [
            plugin.search_files,
            plugin.read_text_file,
            plugin.list_files,
        ]
        chat_options = create_agent_chat_options()
        super().__init__(
            chat_client=chat_client,
            name=name,
            description=description,
            instructions=instructions,
            tools=tools,
            temperature=chat_options.temperature,
            top_p=chat_options.top_p,
            additional_properties={"max_completion_tokens": chat_options.max_tokens},
        )

    def _create_chat_client(
        self,
        deployment_name: str,
        api_key: str,
        base_url: str,
    ) -> AzureOpenAIChatClient:
        """Create an AI chat client for the file search agent using Azure OpenAI.

        Args:
            deployment_name: The model deployment name for Azure AI Inference
            api_key: The API key for Azure AI Inference
            base_url: The endpoint URL for Azure AI Inference
        """
        return AzureOpenAIChatClient(
            deployment_name=deployment_name,
            api_key=api_key,
            endpoint=base_url,
        )


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
    ) -> None:
        instructions = _load_prompt("log_search.txt", flow="default")

        super().__init__(
            name=LOG_SEARCH_AGENT_NAME,
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
        self,
        code_paths: List[str],
        deployment_name: str,
        api_key: str,
        base_url: str,
    ) -> None:
        instructions = _load_prompt("code_search.txt", flow="default")

        super().__init__(
            name=CODE_SEARCH_AGENT_NAME,
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


def extract_final_text(messages: List[ChatMessage]) -> str:
    """
    Extract the final textual output from a list of chat messages.

    This function scans a sequence of ChatMessage objects in order and:
    - Logs non-empty messages authored by "LogSearchAgent" or "CodeSearchAgent".
    - Returns the first non-empty text from a message authored by "SummaryAgent".
    - If no summary is found, falls back to the last message's text if available.
    - Returns an empty string when no suitable text is found.
    """

    for msg in messages:
        author = getattr(msg, "author_name", None)
        text = getattr(msg, "text", None)
        if (
            (author == LOG_SEARCH_AGENT_NAME or author == CODE_SEARCH_AGENT_NAME)
            and isinstance(text, str)
            and text.strip()
        ):
            logger.info(f"{author}: {text.strip()}")
        if author == SUMMARY_AGENT_NAME and isinstance(text, str) and text.strip():
            return text.strip()
    # Fallback: use last message's text or str(content)
    if messages:
        last = messages[-1]
        if isinstance(getattr(last, "text", None), str):
            return cast(str, last.text).strip()
    return ""


async def async_analyze_default(
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: List[str],
    error_message: str,
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
    log_search_agent = LogSearchAgent(
        log_paths=log_folder_path,
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

    # Create summary agent for final answer synthesis
    final_answer_prompt = _load_prompt("final_answer.txt", flow="default")
    chat_options = create_agent_chat_options()
    summary_chat_client = AzureOpenAIChatClient(
        api_key=azure_openai_api_key,
        endpoint=azure_openai_endpoint,
        deployment_name=general_deployment_name,
    )
    summary_agent = ChatAgent(
        chat_client=summary_chat_client,
        name=SUMMARY_AGENT_NAME,
        description="Summarizes and formats final answer.",
        instructions=final_answer_prompt,
        tools=[],
        temperature=chat_options.temperature,
        top_p=chat_options.top_p,
        additional_properties={"max_completion_tokens": chat_options.max_tokens},
    )

    logger.info("Building Sequential workflow...")
    workflow = (
        SequentialBuilder()
        .participants(
            [
                log_search_agent,
                code_search_agent,
                summary_agent,
            ]
        )
        .build()
    )

    logger.info("executing run...")

    async def _run() -> str:
        final_text: str = ""
        async for event in workflow.run_stream(analysis_prompt):
            # Lifecycle: executor invoked
            if isinstance(event, ExecutorInvokedEvent):
                exec_id = getattr(event, "executor_id", None)
                logger.info(f"[ExecutorInvoked] executor={exec_id}")
                continue

            # Lifecycle: executor completed
            if isinstance(event, ExecutorCompletedEvent):
                exec_id = getattr(event, "executor_id", None)
                logger.info(f"[ExecutorCompleted] executor={exec_id}")
                continue

            # Final aggregated output from SequentialBuilder: list[ChatMessage]
            if isinstance(event, WorkflowOutputEvent):
                final_messages = cast(List[ChatMessage], event.data)
                final_text = extract_final_text(final_messages)
                logger.info(final_text)

        return final_text

    async def _run_with_timeout_and_retry(
        coro_factory: Callable[[], Awaitable[str]], timeout_sec: float = 300.0
    ) -> str:
        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await asyncio.wait_for(coro_factory(), timeout=timeout_sec)
            except Exception as e:
                last_exc = e
                logger.info(f"[Magentic] Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries:
                    raise
        raise last_exc if last_exc else RuntimeError("Unknown error")

    value = await _run_with_timeout_and_retry(_run)
    return str(value)
