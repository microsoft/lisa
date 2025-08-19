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
- **Intelligent File Search**: Search across log files with extension filtering and path validation
- **Context-Aware Analysis**: Extracts relevant context around error locations
- **Similarity Scoring**: Uses embeddings to measure analysis quality
- **Comprehensive Logging**: Detailed debug logging for troubleshooting
- **Flexible Input**: Supports both evaluation mode (all test cases) and single test analysis

## Prerequisites

1. **Python 3.12+**
2. **Azure OpenAI Access** with the following deployments:
   - GPT-4.1 or GPT-4o for general analysis
   - GPT-4.1 for software-specific analysis
   - Text-embedding-3-large for similarity calculations
3. **Required Python packages** (install via pip):
   ```bash
   pip install python-dotenv semantic-kernel azure-ai-inference
   ```

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

### Command Line Interface

From `c:\code\lisa\lisa\ai` after activating the venv:

```pwsh
# Analyze all cases defined in data/small_v20250603/inputs.json (default command)
python .\log_agent.py eval

# Analyze a single case by index (0-based, default is 8, range 0-11)
python .\log_agent.py single -t 6
python .\log_agent.py single --test-index 6

# Use a specific analysis flow (choices: 'default', 'gpt-5')
python .\log_agent.py eval --flow default
python .\log_agent.py single -t 6 --flow gpt-5

# Help
python .\log_agent.py --help
```

### Programmatic Usage

You can also use the analyzer programmatically:

```python
from log_agent import analyze
from lisa.util.logger import get_logger

# Get a logger instance
logger = get_logger("my_analyzer")

# Analyze a specific error
result = analyze(
    current_directory="/path/to/lisa/ai",
    azure_openai_api_key="your-api-key",
    azure_openai_endpoint="https://your-resource.openai.azure.com",
    general_deployment_name="gpt-4o",
    software_deployment_name="gpt-4o",
    code_path="/path/to/lisa/code",
    log_folder_path="/path/to/test/logs",
    error_message="Your error message here",
    selected_flow="default",
    logger=logger
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

### Console Output

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

1. **Path validation errors**
   - Ensure log and code paths exist and are accessible
   - Check that paths don't contain restricted characters
   - Verify directory permissions

### Debug Information

Enable detailed logging by checking the generated log files in the `logs/` directory. These contain:

- Complete agent conversations
- Function call details and responses
- API request/response information
- File system operations

