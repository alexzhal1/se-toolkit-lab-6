#!/usr/bin/env python3
"""
Agent that answers questions about the project wiki using tools.
Usage: uv run agent.py "Your question here"
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load configuration
load_dotenv(".env.agent.secret")

LLM_API_BASE = os.getenv("LLM_API_BASE")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")

if not LLM_API_BASE or not LLM_API_KEY or not LLM_MODEL:
    print("Error: LLM_API_BASE, LLM_API_KEY, and LLM_MODEL must be set in .env.agent.secret", file=sys.stderr)
    sys.exit(1)

# Determine project root (where agent.py is located)
PROJECT_ROOT = Path(__file__).parent.absolute()

def safe_path(user_path: str) -> Path:
    """Convert user-provided path to absolute path and ensure it's inside PROJECT_ROOT."""
    target = (PROJECT_ROOT / user_path).resolve()
    if PROJECT_ROOT not in target.parents and target != PROJECT_ROOT:
        raise ValueError(f"Access denied: path '{user_path}' is outside the project directory")
    return target

def read_file(path: str) -> str:
    """Read and return the contents of a file."""
    try:
        full_path = safe_path(path)
        if not full_path.is_file():
            return f"Error: File '{path}' does not exist"
        return full_path.read_text(encoding='utf-8')
    except Exception as e:
        return f"Error reading file: {str(e)}"

def list_files(path: str) -> str:
    """List files and directories in the given path."""
    try:
        full_path = safe_path(path)
        if not full_path.is_dir():
            return f"Error: Path '{path}' is not a directory or does not exist"
        items = sorted([p.name for p in full_path.iterdir()])
        return "\n".join(items) if items else "(empty)"
    except Exception as e:
        return f"Error listing directory: {str(e)}"

# Tool definitions for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project repository. Use this to get the contents of a documentation file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file from the project root (e.g., 'wiki/git-workflow.md')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a given path. Use this to discover available documentation files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from the project root (e.g., 'wiki')"
                    }
                },
                "required": ["path"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a documentation assistant for a software project. Your task is to answer questions using the project's wiki files.

You have access to two tools:
- `list_files(path)`: lists files in a directory. Use it to explore the wiki structure.
- `read_file(path)`: reads the contents of a file. Use it to get details from specific files.

Always prefer to use these tools to find the answer. Start by listing files in the 'wiki' directory to understand what documentation is available. Then read relevant files.

When you find the answer, include the source in your final answer in the format: `source: path#section` (e.g., `source: wiki/git-workflow.md#resolving-merge-conflicts`). If you cannot find the answer, say so.

You may make up to 10 tool calls. After that, you must provide the best answer you have.
"""

def call_llm(messages, tools=None, tool_choice="auto"):
    """Send messages to LLM and return the response."""
    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=0.0,
            timeout=30
        )
        return response.choices[0].message
    except Exception as e:
        print(f"LLM call failed: {e}", file=sys.stderr)
        sys.exit(1)

def execute_tool_call(tool_call):
    """Execute a single tool call and return the result."""
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    print(f"Executing {func_name} with args {args}", file=sys.stderr)

    if func_name == "read_file":
        result = read_file(**args)
    elif func_name == "list_files":
        result = list_files(**args)
    else:
        result = f"Unknown tool: {func_name}"

    return {
        "tool": func_name,
        "args": args,
        "result": result
    }

def main():
    if len(sys.argv) != 2:
        print("Usage: agent.py <question>", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    tool_calls_log = []
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"Iteration {iteration}", file=sys.stderr)

        response_message = call_llm(messages, tools=TOOLS)

        if response_message.tool_calls:
            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                tool_info = execute_tool_call(tool_call)
                tool_calls_log.append(tool_info)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_info["result"]
                })
        else:
            final_answer = response_message.content
            source = ""
            if "source:" in final_answer:
                parts = final_answer.split("source:")
                if len(parts) > 1:
                    source = parts[1].strip().split("\n")[0].strip()
                    final_answer = parts[0].strip()
            else:
                source = "unknown"

            result = {
                "answer": final_answer,
                "source": source,
                "tool_calls": tool_calls_log
            }
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)

    # Max iterations reached – use last assistant message
    last_assistant = [m for m in messages if m["role"] == "assistant"][-1]
    final_answer = last_assistant.get("content", "No answer found after maximum iterations.")
    source = "unknown"
    result = {
        "answer": final_answer,
        "source": source,
        "tool_calls": tool_calls_log
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()