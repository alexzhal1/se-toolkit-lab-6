# Agent Documentation

## Overview
`agent.py` is a CLI tool that answers questions about the project by reading the wiki. It implements an **agentic loop** with two tools: `read_file` and `list_files`. The agent decides when to use tools, executes them, and finally returns a structured JSON answer with the source reference.

## Architecture
- The agent uses the OpenAI-compatible API (OpenRouter) with function calling.
- It loads configuration from `.env.agent.secret`.
- The agentic loop:
  1. Send conversation history (system prompt + user query + previous tool results) and tool definitions to the LLM.
  2. If the LLM requests tool calls, execute them, append results as `tool` messages, and repeat.
  3. If the LLM returns a text message (no tool calls), that is the final answer.
- Maximum 10 tool calls per question to prevent infinite loops.

## Tools

### `read_file`
- **Description**: Reads a file from the project repository.
- **Parameter**: `path` (string) – relative path from project root (e.g., `wiki/git-workflow.md`).
- **Returns**: File contents or an error message.
- **Security**: Prevents directory traversal – any path that resolves outside the project root is rejected.

### `list_files`
- **Description**: Lists files and directories at a given path.
- **Parameter**: `path` (string) – relative directory path from project root (e.g., `wiki`).
- **Returns**: Newline-separated list of entries, or an error.
- **Security**: Same path traversal protection.

## System Prompt
The system prompt instructs the agent:
- To explore the wiki using `list_files` and `read_file`.
- To include the source (file path and optional anchor) in the final answer.
- To stop making tool calls once the answer is ready.

## Output Format
The agent prints a single JSON object to stdout:
```json
{
  "answer": "The answer text...",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {"tool": "list_files", "args": {"path": "wiki"}, "result": "git-workflow.md\n..."},
    {"tool": "read_file", "args": {"path": "wiki/git-workflow.md"}, "result": "..."}
  ]
}
