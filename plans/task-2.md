# Task 2: The Documentation Agent – Implementation Plan

## Overview
This task extends the basic agent from Task 1 by adding two file‑system tools and an agentic loop. The agent will answer questions about the project wiki by reading files and listing directories.

## Tools
- **`read_file(path)`** – returns the content of a file relative to the project root.
- **`list_files(path)`** – returns a newline‑separated list of entries in a directory.

Both tools must prevent directory traversal attacks (no access outside the project root).

## Agentic Loop
1. Send the user question plus tool definitions to the LLM.
2. If the LLM responds with `tool_calls`:
   - Execute each tool, record the result.
   - Append the results as `tool` messages.
   - Repeat (up to 10 iterations).
3. If the LLM responds with a text message (no tool calls), treat it as the final answer.
4. Extract the source reference (the LLM is instructed to include it, e.g., `source: wiki/git-workflow.md#resolving-merge-conflicts`).
5. Output JSON with `answer`, `source`, and `tool_calls` (array of all calls made).

## System Prompt
The system prompt instructs the LLM to:
- Use `list_files` to explore the `wiki/` directory.
- Use `read_file` to read specific files.
- Include the source reference in the final answer.

## Security
Paths are normalized using `Path.resolve()` and checked against the project root. Any attempt to escape (e.g., using `..`) is rejected with an error message.

## Testing
Two regression tests will be added:
- `"How do you resolve a merge conflict?"` – expects a `read_file` call and `git-workflow.md` in the source.
- `"What files are in the wiki?"` – expects a `list_files` call with a path containing `wiki`.