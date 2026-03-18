# Agent Documentation

## Overview
`agent.py` is a CLI tool that answers questions about the project by combining information from the wiki, source code, and live backend API. It implements an **agentic loop** with three tools: `read_file`, `list_files`, and `query_api`. The agent decides which tools to use, executes them, and finally returns a structured JSON answer.

## Architecture
- **LLM Provider**: OpenRouter (free tier) with model `arcee-ai/trinity-large-preview:free`.
- **Configuration**: All settings are read from environment variables:
  - `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL` – from `.env.agent.secret`
  - `LMS_API_KEY` – backend authentication key, from `.env.docker.secret`
  - `AGENT_API_BASE_URL` – backend base URL (default `http://localhost:42002`)
- **Agentic Loop**:
  1. Send conversation history (system prompt + user query + previous tool results) and tool definitions to the LLM.
  2. If the LLM requests tool calls, execute them, append results as `tool` messages, and repeat.
  3. If the LLM returns a text message (no tool calls), that is the final answer.
  4. Maximum 10 tool calls per question prevents infinite loops.

## Tools

### `read_file`
- **Description**: Reads a file from the project repository (wiki or source code).
- **Parameter**: `path` (string) – relative path from project root.
- **Security**: Prevents directory traversal – any path that resolves outside the project root is rejected.

### `list_files`
- **Description**: Lists files and directories at a given path.
- **Parameter**: `path` (string) – relative directory path.
- **Security**: Same path traversal protection.

### `query_api`
- **Description**: Sends an HTTP request to the backend API to fetch live data.
- **Parameters**:
  - `method` (string): GET or POST.
  - `path` (string): API endpoint (e.g., `/items/`, `/analytics/completion-rate?lab=lab-99`).
  - `body` (string, optional): JSON request body for POST.
- **Authentication**: The request includes an `Authorization: Bearer <LMS_API_KEY>` header.
- **Returns**: JSON string with `status_code` and `body`.

## System Prompt
The system prompt instructs the agent on when to use each tool:
- Use `list_files` and `read_file` for wiki or code‑related questions (static facts like framework, ports, status codes).
- Use `query_api` for data‑dependent questions (item count, scores, completion rates).
- If an API call returns an error, consider reading the relevant source code to diagnose the issue.
- Include the source (file path) in the answer when applicable.

## Output Format
The agent prints a single JSON object to stdout:
```json
{
  "answer": "The answer text...",
  "source": "pyproject.toml",
  "tool_calls": [
    {"tool": "read_file", "args": {"path": "pyproject.toml"}, "result": "..."},
    {"tool": "query_api", "args": {"method": "GET", "path": "/items/"}, "result": "{\"status_code\":200,...}"}
  ]
}
