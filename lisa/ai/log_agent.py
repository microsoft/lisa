# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import argparse
import asyncio
import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Union

from retry import retry
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.azure_ai_inference import (
    AzureAIInferenceTextEmbedding,
)

from lisa.ai.default_flow import async_analyze_default

from . import logger

# Constants used in the code
VERBOSITY_LENGTH_THRESHOLD = 1000  # Max length for verbose log messages


def get_current_directory() -> str:
    """Get the working directory for the log analyzer."""
    return os.path.dirname(os.path.realpath(__file__))


@dataclass
class Config:
    """Configuration data class for the log analyzer."""

    azure_openai_api_key: str
    azure_openai_endpoint: str
    embedding_endpoint: str
    general_deployment_name: str
    software_deployment_name: str
    log_root_path: str
    code_path: str
    selected_flow: str


def _load_test_data() -> List[Dict[str, str]]:
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

        logger.debug(f"test data count: {len(test_data)}")
        return test_data

    except FileNotFoundError:
        raise FileNotFoundError(f"inputs.json file not found at {json_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in inputs.json: {e}")


def _cosine_similarity(a: List[float], b: List[float]) -> float:
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


async def _calculate_similarity_async(
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

        # Calculate cosine similarity
        similarity = _cosine_similarity(resp[0], resp[1])
        logger.info(f"Cosine similarity: {similarity}")

        return similarity
    finally:
        await embed.client.close()


def _calculate_similarity(text1: str, text2: str, endpoint: str, api_key: str) -> float:
    """
    Calculate cosine similarity between two texts using AzureAIInferenceTextEmbedding.
    Synchronous wrapper around async implementation.

    Args:
        text1: First text string.
        text2: Second text string.
        endpoint: Azure OpenAI endpoint.
        api_key: Azure OpenAI API key.
    """
    return asyncio.run(
        _calculate_similarity_async(
            text1=text1, text2=text2, endpoint=endpoint, api_key=api_key
        )
    )


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

        logger.debug("verbosity filter applied")

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


def setuplogger() -> str:
    """
    Set up debug logging for all Semantic Kernel operations to a timestamped file.
    Also sets up console logging for INFO level messages.
    This will capture all agent communications, function calls, and LLM interactions.
    """
    debug_dir = os.path.join(get_current_directory(), "logs")
    os.makedirs(debug_dir, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d_%H-%M-%S"
    )
    tracing_filepath = os.path.join(debug_dir, f"debug_{timestamp}.log")

    log_format = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d[%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set the logger level to DEBUG to allow all messages through
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # Create file handler for DEBUG level
    file_handler = logging.FileHandler(tracing_filepath, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

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

    logger.info(f"Debug logging configured. Writing to: {tracing_filepath}")

    return tracing_filepath


def _load_config(selected_flow: str) -> Config:
    """
    Load environment variables and validate required configs.

    Args:
        selected_flow: The analysis flow to use
    """

    # only for individual runs
    from dotenv import load_dotenv

    load_dotenv(os.path.join(get_current_directory(), ".env"))

    # Get environment variables
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    embedding_endpoint = os.getenv("EMBEDDING_ENDPOINT")
    general_deployment_name = os.getenv("GENERAL_DEPLOYMENT_NAME")
    software_deployment_name = os.getenv("SOFTWARE_DEPLOYMENT_NAME")
    log_root_path = os.getenv("LOG_ROOT_PATH")
    # the default folder is the root of LISA code source.
    code_path = os.getenv("CODE_PATH", "../../")

    return Config(
        azure_openai_api_key=azure_openai_api_key,  # type: ignore
        azure_openai_endpoint=azure_openai_endpoint,  # type: ignore
        embedding_endpoint=embedding_endpoint,  # type: ignore
        general_deployment_name=general_deployment_name,  # type: ignore
        software_deployment_name=software_deployment_name,  # type: ignore
        log_root_path=log_root_path,  # type: ignore
        code_path=code_path,
        selected_flow=selected_flow,
    )


def _prepare_test_data(args: argparse.Namespace) -> List[Dict[str, str]]:
    """
    Load and filter test data based on command line arguments.
    """
    test_data = _load_test_data()

    # Check if test_index is provided for single test case analysis
    if hasattr(args, "test_index") and args.test_index is not None:
        if not 0 <= args.test_index < len(test_data):
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


def _get_keywords(answer: Union[Dict[str, List[str]], List[str], str]) -> str:
    """Extract keywords from ground truth data."""
    if isinstance(answer, dict):
        keywords: List[str] = answer.get("problem_keywords", [""])
    elif isinstance(answer, list):
        keywords = answer
    else:
        # ground_truth is a string
        keywords = [answer]

    assert isinstance(keywords, list), f"Expected list, got {type(keywords)}"
    # Sort alphabetically and join.
    keywords_str = ", ".join(sorted(keywords))

    return keywords_str


@retry(tries=3, delay=2)  # type: ignore
def _process_single_test_case(item: Dict[str, Any], config: Config) -> Dict[str, Any]:
    """
    Process a single test case and gather results.

    Args:
        item: Test case data containing path and error_message
        config: Configuration object
    """
    log_folder_path = os.path.join(config.log_root_path, item["path"])

    error_message = item["error_message"]

    generated_text = analyze(
        azure_openai_api_key=config.azure_openai_api_key,
        azure_openai_endpoint=config.azure_openai_endpoint,
        general_deployment_name=config.general_deployment_name,
        software_deployment_name=config.software_deployment_name,
        code_path=config.code_path,
        log_folder_path=log_folder_path,
        error_message=error_message,
        selected_flow=config.selected_flow,
    )

    # Extract keywords
    generated_keywords = _get_keywords(_extract_generated_content(generated_text))
    ground_truth_keywords = _get_keywords(item["ground_truth"])

    logger.info(f"Generated keywords: {generated_keywords}")
    logger.info(f"Ground truth keywords: {ground_truth_keywords}")

    # Calculate similarity
    similarity = _calculate_similarity(
        text1=generated_keywords,
        text2=ground_truth_keywords,
        endpoint=config.embedding_endpoint,
        api_key=config.azure_openai_api_key,
    )

    return {
        "similarity": similarity,
        "generated_keywords": generated_keywords,
        "ground_truth_keywords": ground_truth_keywords,
    }


def _offline_analyze(args: argparse.Namespace, config: Config) -> None:
    """
    Run offline analysis on the provided test data.
    """
    custom_code_path = getattr(args, "code_path", None)
    if custom_code_path:
        config.code_path = custom_code_path

    analyze(
        azure_openai_endpoint=config.azure_openai_endpoint,
        code_path=config.code_path,
        log_folder_path=args.log_folders,
        error_message=args.error_message,
        azure_openai_api_key=config.azure_openai_api_key,
        general_deployment_name=config.general_deployment_name,
        software_deployment_name=config.software_deployment_name,
        selected_flow=config.selected_flow,
    )


def _process_test_cases(
    test_data: List[Dict[str, Any]], config: Config
) -> Dict[str, Any]:
    """
    Process all test cases and gather results.

    Args:
        test_data: List of test case data
        config: Configuration object
    """
    results: Dict[str, List[Any]] = {
        "similarities": [],
        "generated_keywords_list": [],
        "ground_truth_keywords_list": [],
        "test_ids": [],
    }

    for item in test_data:
        logger.info(f"Analyzing test case {item['id']}: {item['path']}")

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
    logger.info("=== DETAILED RESULTS ===")

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
        logger.info(f"Test case {index} (ID: {test_id}): ")
        logger.info(f"  Similarity: {similarity: .6f}")
        logger.info(f"  Generated keywords: {generated}")
        logger.info(f"  Ground truth keywords: {ground_truth}")
        logger.info("")


def _output_summary_statistics(results: Dict[str, Any], config: Config) -> None:
    """
    Output summary statistics for all test cases.
    """
    similarities = results["similarities"]

    logger.info("=== SUMMARY ===")

    # Individual similarities
    for index, similarity in enumerate(similarities):
        logger.info(f"Test case {index} Similarity: {similarity: .6f}")

    logger.info(
        f"General deployment name: {config.general_deployment_name}, "
        f"Software deployment name: {config.software_deployment_name}"
    )

    # Aggregate statistics
    avg_similarity = sum(similarities) / len(similarities)
    logger.info(
        f"Average similarity: {avg_similarity: .6f}, "
        f"Best: {max(similarities): .6f}, "
        f"Worst: {min(similarities): .6f}, "
        f"Total test cases: {len(similarities)}"
    )


def _output_results(results: Dict[str, Any], config: Config) -> None:
    """
    Output detailed results and summary statistics.
    """
    if not results["similarities"]:
        logger.info("No results to display.")
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
    setuplogger()

    if args.command == "analyze":
        _offline_analyze(args, config)
    else:
        # Load and filter test data
        test_data = _prepare_test_data(args)

        # Process test cases
        results = _process_test_cases(test_data, config)

        _output_results(results, config)


def _add_flow_argument(parser: argparse.ArgumentParser) -> None:
    """
    Add the --flow argument to a parser.

    Args:
        parser: The ArgumentParser to add the --flow argument to
    """
    parser.add_argument(
        "--flow",
        choices=["default", "gpt-5"],
        default="default",
        help=(
            "Select the analysis flow to use. Choices: 'default', 'gpt-5'. "
            "(default: 'default')"
        ),
    )


def parse_args() -> argparse.Namespace:
    """
    Set up and parse command line arguments for the log analyzer agent.
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(description="AI Log Analyzer Agent")
    subparsers = parser.add_subparsers(dest="command")

    # 'eval' subcommand (default) - now handles both single and all test cases
    eval_parser = subparsers.add_parser(
        "eval",
        help=(
            "Run evaluation on test cases (default). "
            "Use -t to analyze a single case, otherwise analyzes all."
        ),
    )
    eval_parser.add_argument(
        "-t",
        "--test-index",
        type=int,
        default=None,
        help=(
            "Index of the test case to analyze. "
            "If not provided, analyzes all test cases (ranging 0-11)"
        ),
    )
    _add_flow_argument(eval_parser)

    # 'analyze' subcommand
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze an error message across multiple log folders"
    )
    analyze_parser.add_argument(
        "-l",
        "--log-folders",
        nargs="+",
        required=True,
        help="List of log folder paths to analyze",
    )
    analyze_parser.add_argument(
        "-e",
        "--error-message",
        default="",
        help="Error message to analyze (optional)",
    )
    analyze_parser.add_argument(
        "-c",
        "--code-path",
        default=None,
        help="Path to the code folder (default: LISA root path)",
    )
    _add_flow_argument(analyze_parser)

    parser.set_defaults(command="eval")

    return parser.parse_args()


async def _async_analyze_gpt5(
    azure_openai_api_key: str,
    azure_openai_endpoint: str,
    general_deployment_name: str,
    software_deployment_name: str,
    code_path: str,
    log_folder_path: List[str],
    error_message: str,
) -> str:
    """
    GPT-5 specific async analysis method.
    This is a placeholder for future GPT-5 specific implementation.
    """
    # For now, use the same implementation as default
    # This can be extended with GPT-5 specific logic in the future
    logger.info("Using GPT-5 analysis flow")
    return await async_analyze_default(
        azure_openai_api_key=azure_openai_api_key,
        azure_openai_endpoint=azure_openai_endpoint,
        general_deployment_name=general_deployment_name,
        software_deployment_name=software_deployment_name,
        code_path=code_path,
        log_folder_path=log_folder_path,
        error_message=error_message,
    )


def analyze(
    azure_openai_endpoint: str,
    code_path: str,
    log_folder_path: Union[str, List[str]],
    error_message: str,
    general_deployment_name: str = "gpt-4o",
    software_deployment_name: str = "gpt-4.1",
    selected_flow: str = "default",
) -> str:
    """
    Analyze logs using async agents with asyncio.run for execution.
    Supports different analysis flows based on selected_flow parameter.
    """

    # Select the appropriate analysis method based on selected_flow
    if selected_flow == "gpt-5":
        async_analyze_func = _async_analyze_gpt5
    else:  # default flow
        async_analyze_func = async_analyze_default

    if isinstance(log_folder_path, str):
        log_folder_path = [log_folder_path]

    logger.info(f"Using analysis flow: {selected_flow}")

    return asyncio.run(
        async_analyze_func(
            azure_openai_api_key=azure_openai_api_key,
            azure_openai_endpoint=azure_openai_endpoint,
            general_deployment_name=general_deployment_name,
            software_deployment_name=software_deployment_name,
            code_path=code_path,
            log_folder_path=log_folder_path,
            error_message=error_message,
        )
    )


if __name__ == "__main__":
    main()
