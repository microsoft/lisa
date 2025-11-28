# LISA AI Log Analyzer

A sophisticated multi-agent AI system for analyzing LISA (Linux Infrastructure and Services Automation) test logs and identifying root causes of failures. This tool uses Azure OpenAI's GPT models with specialized agents to search through log files and source code, providing comprehensive error analysis.

## Overview

The LISA AI Log Analyzer consists of:

- **LogSearchAgent**: Specialized in searching and analyzing log files for error patterns
- **CodeSearchAgent**: Examines source code files and analyzes implementations related to errors
- **Magentic Orchestration**: Coordinates the agents to provide comprehensive analysis
- **File Search Plugin**: Provides file system access capabilities to the agents

## Features

- **Multi-Agent Analysis**: Combines log analysis and code inspection for comprehensive error diagnosis
- **Real-world Troubleshooting**: Analyze specific error messages across multiple log folders with the `analyze` command
- **Intelligent File Search**: Search across log files with extension filtering and path validation
- **Context-Aware Analysis**: Extracts relevant context around error locations
- **Similarity Scoring**: Uses embeddings to measure analysis quality
- **Comprehensive Logging**: Detailed debug logging for troubleshooting
- **Flexible Input**: Supports evaluation mode (all test cases), single test analysis, and custom error analysis
- **Multiple Analysis Flows (TODO)**: Choose between 'default' and 'gpt-5' analysis flows

## Prerequisites

1. **Python 3.12+**
2. **Azure OpenAI Access** with the following deployments:
   - GPT-4.1 or GPT-4o for general analysis
   - GPT-4.1 for software-specific analysis
   - Text-embedding-3-large for similarity calculations
3. **Required Python packages** (install via pip):
   ```bash
   pip install python-dotenv semantic-kernel azure-ai-inference, retry
   ```

## Quick Start for Error Analysis

To quickly analyze a test failure using the AI log analyzer:

1. **Set up configuration** (see Setup section below for details)
2. **Navigate to the LISA directory:**
   ```bash
   cd c:\code\lisa
   ```
3. **Run the analyze command:**
   ```pwsh
   python -m lisa.ai.log_agent analyze -l "C:\path\to\your\log\folder" -e "Your error message here"
   ```

   Or without an error message to analyze all logs in the folder:
   ```pwsh
   python -m lisa.ai.log_agent analyze -l "C:\path\to\your\log\folder"
   ```

This will provide AI-powered analysis of your error message within the context of your log files and the LISA codebase.

## Setup

Copy the template configuration file and fill in your details:

```bash
cp .env.template .env
```

Edit `.env` with your Azure OpenAI credentials and paths:

```bash
# Azure OpenAI Configuration (Required)
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
GENERAL_DEPLOYMENT_NAME=gpt-4o
SOFTWARE_DEPLOYMENT_NAME=gpt-4.1

# Embedding Configuration
EMBEDDING_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-large

# File System Paths
LOG_ROOT_PATH=/path/to/your/test/data/root
CODE_PATH=/path/to/your/lisa/code/repository
```

## Usage

The LISA AI Log Analyzer supports three different modes of operation:

### 1. Evaluation Mode (`eval`)
Runs analysis on all predefined test cases from `data/small_v20250603/inputs.json`, or analyzes a specific test case by index if the `-t` option is provided. This mode is primarily used for testing and evaluating the analyzer's performance.

### 2. Custom Error Analysis (`analyze`)
**This is the primary mode for real-world troubleshooting.** Analyze specific error messages across your own log folders, or perform general log analysis when no specific error message is provided. This mode is designed for production use when you encounter test failures and need AI-powered analysis.

### Command Line Interface

From the LISA root directory (`c:\code\lisa`) after activating the venv:

```pwsh
# Analyze all cases defined in data/small_v20250603/inputs.json (default command)
python -m lisa.ai.log_agent eval

# Analyze a single case by index (0-based, range 0-11)
python -m lisa.ai.log_agent eval -t 6
python -m lisa.ai.log_agent eval --test-index 6

# Analyze an error message across multiple log folders (analyze command)
python -m lisa.ai.log_agent analyze -l "C:\path\to\log\folder1" "C:\path\to\log\folder2" -e "Exception: Random test exception occurred"

# Analyze logs without a specific error message (general log analysis)
python -m lisa.ai.log_agent analyze -l "C:\path\to\log\folder1" "C:\path\to\log\folder2"

# Use a specific analysis flow (choices: 'default', 'gpt-5')
python -m lisa.ai.log_agent eval --flow default
python -m lisa.ai.log_agent eval -t 6 --flow gpt-5
python -m lisa.ai.log_agent analyze -l "C:\path\to\logs" -e "Error message" --flow gpt-5

# Help
python -m lisa.ai.log_agent --help
```

#### Analyze Command Details

The `analyze` command is designed for real-world troubleshooting scenarios where you have specific log folders and error messages to investigate:

**Required Parameters:**
- `-l, --log-folders`: One or more log folder paths to analyze

**Optional Parameters:**
- `-e, --error-message`: The error message you want to analyze (optional - if not provided, performs general log analysis)
- `-c, --code-path`: Path to the code folder (defaults to LISA root path)
- `--flow`: Select the analysis flow ('default' or 'gpt-5', default: 'default')

**Examples:**

```pwsh
# Analyze with a specific error message
python -m lisa.ai.log_agent analyze -l "C:\path\to\log1" "C:\path\to\log2" -e "Connection timeout error"

# General log analysis without specific error message
python -m lisa.ai.log_agent analyze -l "C:\path\to\log1" "C:\path\to\log2"

# Custom code path with specific error
python -m lisa.ai.log_agent analyze -l "C:\path\to\logs" -e "Import error" -c "C:\custom\path\to\lisa"
```

### Programmatic Usage

You can also use the analyzer programmatically:

```python
from log_agent import analyze
from lisa.util.logger import get_logger

# Get a logger instance
logger = get_logger("my_analyzer")

# Analyze a specific error across multiple log folders
result = analyze(
    azure_openai_api_key="your-api-key",
    azure_openai_endpoint="https://your-resource.openai.azure.com",
    general_deployment_name="gpt-4o",
    software_deployment_name="gpt-4o",
    code_path="/path/to/lisa/code",
    log_folder_path=["/path/to/test/logs1", "/path/to/test/logs2"],  # Can be string or list
    error_message="Your error message here",  # Optional - can be empty string for general analysis
    selected_flow="default",
)

print(result)
```

## How It Works

### Analysis Workflow

1. **Initial Error Search**: The system searches for the exact error message in log files
2. **Code Review**: If there's a call trace, it examines the related code for defects
3. **Hypothesis Generation**: Generates top 3 possible reasons for failures
4. **Evidence Gathering**: Searches and analyzes logs for each possible reason
5. **Root Cause Analysis**: Summarizes the most likely reasons for failure

### Agent Coordination

The system uses **Magentic Orchestration** to coordinate multiple specialized agents:

- Agents work collaboratively to analyze different aspects (logs vs code)
- A manager agent synthesizes findings into a comprehensive final answer
- Built-in retry logic and timeout protection ensure reliability

### File Search Capabilities

The FileSearchPlugin provides powerful search capabilities:

- **Extension Filtering**: Search specific file types (`.log`, `.txt`, etc.)
- **Pattern Matching**: Find exact strings or patterns in files
- **Context Extraction**: Read specific line ranges around matches
- **Path Validation**: Ensures secure file access within allowed directories

## Output

### Console Output for Analyze Command

When using the `analyze` command, the system will:

1. **Search for the error message** in the provided log folders (if an error message is provided)
2. **Examine relevant code** if call traces are found
3. **Generate hypotheses** about the root cause
4. **Provide actionable insights** and troubleshooting steps

The output includes:
- **Root cause analysis** of the specific error
- **Relevant code sections** that may be involved
- **Contextual log information** around the error or interesting log patterns
- **Recommended troubleshooting steps**
- **Potential fixes or workarounds**

### Debug Logs

Detailed debug logs are saved to `logs/debug_TIMESTAMP.log` containing:

- Agent communications and function calls
- LLM interactions and responses
- File search operations
- Error details and stack traces

### Evaluation Metrics

When running in evaluation mode, the system outputs:

- Individual test case results and similarity scores
- Average, best, and worst similarity scores
- Detailed analysis for each test case
- Summary statistics

## Troubleshooting

### Common Issues

1. **Azure OpenAI API errors**
   - Verify your API key and endpoint are correct
   - Check deployment names match your Azure OpenAI resource
   - Ensure sufficient quota for your deployments

2. **Path validation errors**
   - Ensure log and code paths exist and are accessible
   - Check that paths don't contain restricted characters
   - Verify directory permissions

### Debug Information

Enable detailed logging by checking the generated log files in the `logs/` directory. These contain:

- Complete agent conversations
- Function call details and responses
- API request/response information
- File system operations

