# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import os
from collections import deque
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
from .common import (
    AGENT_MAX_TOKENS,
    AGENT_TEMPERATURE,
    AGENT_TOP_P,
    get_current_directory,
)

# Define agent name constants
LOG_SEARCH_AGENT_NAME = "LogSearchAgent"
CODE_SEARCH_AGENT_NAME = "CodeSearchAgent"
SUMMARY_AGENT_NAME = "SummaryAgent"
MAX_SEARCH_CONTEXT_ITEMS = 200
MAX_MATCHED_TEXT_CHARS = 500
MAX_READ_LINE_COUNT = 300
MAX_READ_TEXT_CHARS = 30000
MAX_LIST_FILES_RETURN = 200


def _chat_message_to_text(message: Any) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text

    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content

    if content is not None:
        return str(content)

    return str(message)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    truncated_count = len(text) - max_chars
    logger.info(
        f"Truncating text from {len(text)} chars to {max_chars} chars, "
        f"truncated {truncated_count} chars."
    )
    return f"{text[:max_chars]}\n...[truncated {truncated_count} chars]"


def _collapse_consecutive_duplicate_lines(
    lines: List[tuple[int, str]],
    *,
    max_consecutive: int = 10,
) -> tuple[List[tuple[int, str]], int]:
    """Collapse consecutive duplicated lines.

    If the same line text repeats consecutively more than max_consecutive times,
    keep the first max_consecutive occurrences (with their original line numbers)
    and insert a single placeholder line indicating how many were omitted.

    Returns:
        (collapsed_lines, omitted_count)
    """

    max_consecutive = max(max_consecutive, 1)

    collapsed: List[tuple[int, str]] = []
    omitted_total = 0

    i = 0
    while i < len(lines):
        _line_no, text = lines[i]

        # Count run length.
        run_end = i + 1
        while run_end < len(lines) and lines[run_end][1] == text:
            run_end += 1

        run_len = run_end - i
        if run_len <= max_consecutive:
            collapsed.extend(lines[i:run_end])
        else:
            collapsed.extend(lines[i : i + max_consecutive])
            omitted = run_len - max_consecutive
            omitted_total += omitted
            first_omitted_line = lines[i + max_consecutive][0]
            last_omitted_line = lines[run_end - 1][0]
            collapsed.append(
                (
                    first_omitted_line,
                    f"...[omitted {omitted} repeated lines (same as above) "
                    f"from line {first_omitted_line} to {last_omitted_line}]",
                )
            )

        i = run_end

    return collapsed, omitted_total


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

    def get_file_stats(self, file_path: str) -> Dict[str, Any]:
        """Return basic file stats to help the agent decide how to page/scan logs.

        Args:
            file_path: The path to the file.

        Returns:
            Dict with size_bytes, total_lines, and file_path.
        """

        valid_result = self._valid_path(file_path)
        if valid_result:
            return valid_result

        norm_path = os.path.normpath(file_path)
        if not os.path.exists(norm_path):
            return {"error": f"File not found: {norm_path}"}
        if not os.path.isfile(norm_path):
            return {"error": f"Path is not a file: {norm_path}"}

        try:
            size_bytes = os.path.getsize(norm_path)
            total_lines = 0
            with open(norm_path, "r", encoding="utf-8", errors="replace") as f:
                for _ in f:
                    total_lines += 1
        except Exception as e:
            return {"error": f"Error getting file stats {norm_path}: {e}"}

        return {
            "file_path": os.path.abspath(norm_path),
            "size_bytes": size_bytes,
            "total_lines": total_lines,
        }

    def _iter_candidate_files_for_search(
        self, base_path: str, allowed_extensions: List[str]
    ) -> Any:
        for root, dirs, files in os.walk(base_path):
            dirs.sort()
            files.sort()
            for file in files:
                file_path = os.path.join(root, file)

                # Skip files that in . started path, like .nox, .vscode.
                if os.path.relpath(file_path, base_path).startswith("."):
                    continue

                # Apply file extension filter
                _, file_ext = os.path.splitext(file_path.lower())
                if file_ext not in allowed_extensions:
                    continue

                yield file_path

    def _scan_file_for_search(
        self,
        file_path: str,
        search_string: str,
        match_offset: int,
        page_size: int,
        matches_seen: int,
        returned: int,
    ) -> tuple[int, int, bool, List[Dict[str, Union[str, int]]]]:
        entries: List[Dict[str, Union[str, int]]] = []
        found_extra = False

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                line_content = line.strip().lower()
                if search_string not in line_content:
                    continue

                matches_seen += 1

                # Skip matches until we reach the requested offset.
                if matches_seen <= match_offset:
                    continue

                # Page full; one more match indicates another page.
                if returned >= page_size:
                    found_extra = True
                    break

                entries.append(
                    {
                        # Ensure we use the absolute, normalized path
                        "file_path": os.path.abspath(file_path),
                        # Use 1-based line numbers (read_text_file expects 1-based).
                        "match_line_number": i,
                        "matched_text": _truncate_text(
                            line_content,
                            MAX_MATCHED_TEXT_CHARS,
                        ),
                    }
                )
                returned += 1

        return matches_seen, returned, found_extra, entries

    def search_files(
        self,
        search_string: str,
        path: str,
        file_extensions: str,
        max_matches: int = MAX_SEARCH_CONTEXT_ITEMS,
        match_offset: int = 0,
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
            max_matches: Maximum number of matches to return in this call (page size).
                         The actual returned size is capped for safety.
            match_offset: Number of matches to skip (for pagination). 0-based.

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

        if match_offset < 0:
            return {"error": f"Invalid match_offset: {match_offset}. Must be >= 0."}

        max_matches = max(max_matches, 1)

        # Enforce a safety cap per call.
        page_size = min(max_matches, MAX_SEARCH_CONTEXT_ITEMS)

        # Combined results
        log_context: Dict[str, Any] = {"context": []}

        files_found = 0

        # Parse comma-separated extensions and normalize to lowercase
        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        allowed_extensions = extensions

        logger.info(
            f"Searching for '{search_string}' in {path} "
            f"with extensions {extensions} "
            f"(match_offset={match_offset}, page_size={page_size})"
        )

        matches_seen = 0
        returned = 0
        found_extra = False

        # Search both standard logs and serial logs
        for file_path in self._iter_candidate_files_for_search(
            path, allowed_extensions
        ):
            files_found += 1
            try:
                (
                    matches_seen,
                    returned,
                    found_extra,
                    entries,
                ) = self._scan_file_for_search(
                    file_path,
                    search_string,
                    match_offset,
                    page_size,
                    matches_seen,
                    returned,
                )
                log_context["context"].extend(entries)
            except Exception as e:
                logger.info(f"Error processing file {file_path}: {str(e)}")

            # Stop scanning files once we know there is another page.
            if found_extra:
                break

        has_more = found_extra
        next_match_offset = match_offset + page_size if has_more else None

        match_count = len(log_context["context"])
        logger.info(
            f"Searched '{search_string}', {files_found} files processed, "
            f"{match_count} matches found."
        )
        log_context["pagination"] = {
            "match_offset": match_offset,
            "page_size": page_size,
            "returned_matches": match_count,
            "matches_seen": matches_seen,
            "has_more": has_more,
            "next_match_offset": next_match_offset,
            "max_matches_per_call": MAX_SEARCH_CONTEXT_ITEMS,
        }
        return log_context

    def read_text_file(
        self, start_line_offset: int, file_path: str, line_count: int
    ) -> Dict[str, Any]:
        """
        Extracts lines from a file starting from a specific line number.

        Args:
            start_line_offset: The line number to start reading from (1-based)
            file_path: The path to the file to read
            line_count: Number of lines to read

        Returns:
            Dictionary containing either file content/metadata or error information
        """

        raw_lines: List[tuple[int, str]] = []
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
        bounded_line_count = min(max(1, line_count), MAX_READ_LINE_COUNT)
        traceback_end = traceback_start + bounded_line_count - 1

        try:
            with open(norm_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, start=1):
                    if traceback_start <= i <= traceback_end:
                        raw_lines.append((i, line.rstrip()))
                    if i > traceback_end:
                        break

            logger.info(f"Successfully extracted {len(raw_lines)} lines of context")
        except Exception as e:
            error_message = f"Error reading file {norm_path}: {str(e)}"
            logger.info(error_message)
            return {"error": error_message}

        read_line_count = len(raw_lines)
        read_end_line = raw_lines[-1][0] if raw_lines else traceback_start - 1

        collapsed_lines, omitted_repeated = _collapse_consecutive_duplicate_lines(
            raw_lines, max_consecutive=10
        )
        returned_line_count = len(collapsed_lines)
        returned_end_line = (
            collapsed_lines[-1][0] if collapsed_lines else traceback_start - 1
        )
        formatted_lines = [f"({i}): {t}" for i, t in collapsed_lines]

        result = "\n".join(formatted_lines)
        was_truncated_by_chars = len(result) > MAX_READ_TEXT_CHARS
        result = _truncate_text(result, MAX_READ_TEXT_CHARS)
        logger.debug(f"read_text_file result: {result}")

        return {
            "content": result,
            "metadata": {
                "file_path": os.path.abspath(norm_path),
                "requested_start_line": start_line_offset,
                "effective_start_line": traceback_start,
                "requested_line_count": line_count,
                # NOTE: "effective_*" reflects what the tool actually returned,
                # not the idealized request window. This makes paging/tool limits
                # observable even when EOF is reached early or duplicates collapse.
                "effective_line_count": returned_line_count,
                "effective_end_line": returned_end_line,
                # Preserve additional observability for debugging.
                "requested_end_line": traceback_end,
                "bounded_requested_line_count": bounded_line_count,
                "read_line_count": read_line_count,
                "read_end_line": read_end_line,
                "returned_end_line": returned_end_line,
                "max_read_line_count": MAX_READ_LINE_COUNT,
                "max_read_text_chars": MAX_READ_TEXT_CHARS,
                "was_truncated_by_chars": was_truncated_by_chars,
                "collapsed_consecutive_duplicates": {
                    "max_consecutive": 10,
                    "omitted_repeated_lines": omitted_repeated,
                },
            },
        }

    def read_text_file_tail(self, file_path: str, line_count: int) -> Dict[str, Any]:
        """Read the last N lines of a text file (bounded by MAX_READ_LINE_COUNT).

        This is useful for serial console logs where the root cause often appears
        near the end (e.g., stack traces, emergency mode, unit failures).
        """

        valid_result = self._valid_path(file_path)
        if valid_result:
            return valid_result

        norm_path = os.path.normpath(file_path)
        if not os.path.exists(norm_path):
            return {"error": f"File not found: {norm_path}"}

        bounded_line_count = min(max(1, line_count), MAX_READ_LINE_COUNT)

        try:
            tail: deque[tuple[int, str]] = deque(maxlen=bounded_line_count)
            with open(norm_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, start=1):
                    tail.append((i, line.rstrip()))
        except Exception as e:
            return {"error": f"Error reading file {norm_path}: {e}"}

        if not tail:
            return {
                "content": "",
                "metadata": {
                    "file_path": os.path.abspath(norm_path),
                    "requested_line_count": line_count,
                    "effective_line_count": 0,
                    "effective_start_line": 0,
                    "effective_end_line": 0,
                    "max_read_line_count": MAX_READ_LINE_COUNT,
                },
            }

        collapsed_lines, omitted_repeated = _collapse_consecutive_duplicate_lines(
            list(tail), max_consecutive=10
        )

        read_line_count = len(tail)
        read_start_line = tail[0][0]
        read_end_line = tail[-1][0]
        returned_line_count = len(collapsed_lines)
        returned_end_line = collapsed_lines[-1][0] if collapsed_lines else read_end_line

        start_line = collapsed_lines[0][0]
        end_line = collapsed_lines[-1][0]
        content = "\n".join(f"({i}): {t}" for i, t in collapsed_lines)
        was_truncated_by_chars = len(content) > MAX_READ_TEXT_CHARS
        content = _truncate_text(content, MAX_READ_TEXT_CHARS)

        return {
            "content": content,
            "metadata": {
                "file_path": os.path.abspath(norm_path),
                "requested_line_count": line_count,
                # "effective_*" reflects what the tool actually returned.
                "effective_line_count": returned_line_count,
                "effective_start_line": start_line,
                "effective_end_line": end_line,
                "read_line_count": read_line_count,
                "read_start_line": read_start_line,
                "read_end_line": read_end_line,
                "returned_end_line": returned_end_line,
                "collapsed_display_start_line": start_line,
                "collapsed_display_end_line": end_line,
                "max_read_line_count": MAX_READ_LINE_COUNT,
                "max_read_text_chars": MAX_READ_TEXT_CHARS,
                "was_truncated_by_chars": was_truncated_by_chars,
                "collapsed_consecutive_duplicates": {
                    "max_consecutive": 10,
                    "omitted_repeated_lines": omitted_repeated,
                },
            },
        }

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
        end = min(offset + max_files, total_files, offset + MAX_LIST_FILES_RETURN)
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
            plugin.read_text_file_tail,
            plugin.get_file_stats,
            plugin.list_files,
        ]
        super().__init__(
            chat_client=chat_client,
            name=name,
            description=description,
            instructions=instructions,
            tools=tools,
            temperature=AGENT_TEMPERATURE,
            top_p=AGENT_TOP_P,
            additional_properties={"max_completion_tokens": AGENT_MAX_TOKENS},
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


def _find_latest_serial_console_log_path(
    log_folder_path: List[str],
) -> Optional[str]:
    """
    Find serial_console.log under provided log paths.

    If multiple files are found, select the last one
    """

    latest_serial_log_path: Optional[str] = None

    for base_path in log_folder_path:
        normalized_base_path = os.path.normpath(base_path)

        if not os.path.exists(normalized_base_path):
            continue

        for root, dirs, files in os.walk(normalized_base_path):
            dirs.sort()
            files.sort()
            for file_name in files:
                if "serial_console.log" not in file_name:
                    continue

                latest_serial_log_path = os.path.abspath(os.path.join(root, file_name))

    return latest_serial_log_path


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

    trigger_keywords = [
        "cannot connect to",
        "OSProvisioningTimedOut",
        "failed to connect",
        "KernelPanicException",
    ]
    normalized_error_message = error_message.lower()
    do_search_serial_console_log = any(
        keyword in normalized_error_message for keyword in trigger_keywords
    )

    serial_console_log_path: Optional[str] = None
    serial_console_prompt_block = ""
    if do_search_serial_console_log:
        serial_console_log_path = _find_latest_serial_console_log_path(log_folder_path)
        if serial_console_log_path:
            logger.info(f"Selected serial_console.log: {serial_console_log_path}")
        else:
            logger.info("serial_console.log not found under provided log_folder_path")

        serial_console_prompt_block = (
            f"**SELECTED SERIAL CONSOLE LOG PATH: **\n{serial_console_log_path}\n"
        )

    # Include the actual error message in the analysis prompt
    analysis_prompt = f"""{system_instructions}
**ERROR MESSAGE TO ANALYZE: **
{error_message}
**AVAILABLE LOG PATHS: **
{log_folder_path}
{serial_console_prompt_block}
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
        temperature=AGENT_TEMPERATURE,
        top_p=AGENT_TOP_P,
        additional_properties={"max_completion_tokens": AGENT_MAX_TOKENS},
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
        max_retries = 2
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(coro_factory(), timeout=timeout_sec)
            except Exception as e:
                last_exc = e
                logger.info(f"Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
        raise last_exc if last_exc else RuntimeError("Unknown error")

    value = await _run_with_timeout_and_retry(_run)
    return str(value)
