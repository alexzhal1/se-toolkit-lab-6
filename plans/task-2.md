# Task 2 Implementation Plan: The Documentation Agent

## Overview
Extend `agent.py` from Task 1 with an agentic loop that can call tools (`read_file`, `list_files`) to navigate the project wiki and answer questions. The agent will:
1. Send the user query plus tool definitions to the LLM.
2. If the LLM responds with tool calls, execute them and feed results back.
3. Repeat until the LLM returns a final answer (no tool calls) or a maximum of 10 iterations.
4. Output JSON with `answer`, `source`, and `tool_calls` (full history).

## Tool Schemas (OpenAI Function Calling)
- `read_file`: reads a file given a relative path. Parameters: `path` (string).
- `list_files`: lists contents of a directory. Parameters: `path` (string).

Both tools must enforce security: prevent path traversal outside the project root.

## Agentic Loop Implementation
- Use the OpenAI client with the `tools` parameter.
- Maintain a conversation history: system prompt, user query, and all assistant/tool messages.
- Loop:
  - Send history + tools to LLM.
  - Extract response: if `tool_calls` present, execute each, append tool response messages, continue.
  - If no tool calls, take the assistant message as final answer and break.
- After loop, extract `source` from the final answer (the LLM should include it in the text; we may parse or trust that it's there). The spec requires `source` as a separate field – we will attempt to extract it from the final message or default to an empty string.
- Collect all tool calls made into the `tool_calls` output array.

## System Prompt Strategy
The system prompt instructs the LLM:
- It is a documentation agent with access to a wiki.
- Use `list_files` to explore available wiki files.
- Use `read_file` to read file contents.
- When answering, include the source file (and optional anchor) in the answer text (e.g., "See wiki/file.md#section").
- Respond in the final message without tool calls.

## Security
- Resolve paths relative to the project root (current working directory).
- Use `os.path.abspath` and ensure the resolved path starts with the project root to prevent `../` escapes.

## Testing
Add two regression tests:
1. Question: "How do you resolve a merge conflict?" – Expect `read_file` tool call on `wiki/git-workflow.md` and source containing that file.
2. Question: "What files are in the wiki?" – Expect `list_files` tool call on `wiki` and source referencing that listing.

## Dependencies
- No new dependencies beyond Task 1 (`openai`, `python-dotenv`).
