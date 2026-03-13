#!/usr/bin/env python3
"""
Agent that answers questions about the project using wiki files and the live backend API.
Usage: uv run agent.py "Your question here"
"""

import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load configuration
load_dotenv(".env.agent.secret")  # for LLM config
load_dotenv(".env.docker.secret") # for LMS_API_KEY (backend key)

LLM_API_BASE = os.getenv("LLM_API_BASE")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")
LMS_API_KEY = os.getenv("LMS_API_KEY")
AGENT_API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")

if not LLM_API_BASE or not LLM_API_KEY or not LLM_MODEL:
    print("Error: LLM_API_BASE, LLM_API_KEY, and LLM_MODEL must be set in .env.agent.secret", file=sys.stderr)
    sys.exit(1)
if not LMS_API_KEY:
    print("Warning: LMS_API_KEY not set, query_api may fail for authenticated endpoints", file=sys.stderr)

PROJECT_ROOT = Path(__file__).parent.absolute()

def safe_path(user_path: str) -> Path:
    target = (PROJECT_ROOT / user_path).resolve()
    if PROJECT_ROOT not in target.parents and target != PROJECT_ROOT:
        raise ValueError(f"Access denied: path '{user_path}' is outside the project directory")
    return target

def read_file(path: str) -> str:
    try:
        full_path = safe_path(path)
        if not full_path.is_file():
            return f"Error: File '{path}' does not exist"
        return full_path.read_text(encoding='utf-8')
    except Exception as e:
        return f"Error reading file: {str(e)}"

def list_files(path: str) -> str:
    try:
        full_path = safe_path(path)
        if not full_path.is_dir():
            return f"Error: Path '{path}' is not a directory or does not exist"
        items = sorted([p.name for p in full_path.iterdir()])
        return "\n".join(items) if items else "(empty)"
    except Exception as e:
        return f"Error listing directory: {str(e)}"

def query_api(method: str, path: str, body: str = None) -> str:
    """Make an HTTP request to the backend API."""
    url = AGENT_API_BASE_URL.rstrip('/') + '/' + path.lstrip('/')
    headers = {}
    if LMS_API_KEY:
        headers["Authorization"] = f"Bearer {LMS_API_KEY}"
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        elif method.upper() == "POST":
            resp = requests.post(url, headers=headers, json=json.loads(body) if body else None, timeout=10)
        elif method.upper() == "PUT":
            resp = requests.put(url, headers=headers, json=json.loads(body) if body else None, timeout=10)
        elif method.upper() == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=10)
        else:
            return json.dumps({"status_code": 400, "body": f"Unsupported method: {method}"})
        return json.dumps({
            "status_code": resp.status_code,
            "body": resp.text
        })
    except Exception as e:
        return json.dumps({"status_code": 500, "body": f"Request failed: {str(e)}"})

# Tool definitions
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project repository. Use this to get the contents of a documentation or source code file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file from the project root (e.g., 'wiki/git-workflow.md' or 'backend/app.py')"
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
            "description": "List files and directories at a given path. Use this to discover available documentation or source code files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from the project root (e.g., 'wiki' or 'backend')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Send an HTTP request to the backend API. Use this to get live data from the system (e.g., item counts, scores) or to test endpoints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE"],
                        "description": "HTTP method"
                    },
                    "path": {
                        "type": "string",
                        "description": "API endpoint path (e.g., '/items/' or '/analytics/completion-rate?lab=lab-99')"
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON request body for POST/PUT requests"
                    }
                },
                "required": ["method", "path"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a system agent for a software project. Your task is to answer questions using three sources:
1. Project wiki files (using `list_files` and `read_file`).
2. Source code files (using `read_file` on paths like 'backend/app.py').
3. Live backend API (using `query_api` to fetch dynamic data).

Guidelines:
- For documentation questions (e.g., "How do I resolve a merge conflict?"), use `list_files` on 'wiki' and then `read_file` on relevant files.
- For static system facts (e.g., "What framework does the backend use?"), read the source code (e.g., 'backend/requirements.txt' or 'backend/app.py').
- For data queries (e.g., "How many items are in the database?"), use `query_api` with the appropriate endpoint (e.g., GET /items/).
- For debugging, you may need to chain tools: first query an API endpoint to see the error, then read the source code to find the buggy line.

When you find the answer, include the source if applicable (e.g., `source: wiki/file.md#section` or `source: API endpoint`). If no source, omit the source field.

You may make up to 10 tool calls. After that, provide the best answer you have.
"""

def call_llm(messages, tools=None, tool_choice="auto"):
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
    func_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    print(f"Executing {func_name} with args {args}", file=sys.stderr)

    if func_name == "read_file":
        result = read_file(**args)
    elif func_name == "list_files":
        result = list_files(**args)
    elif func_name == "query_api":
        result = query_api(**args)
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
            final_answer = response_message.content or ""
            source = ""
            if "source:" in final_answer:
                parts = final_answer.split("source:")
                if len(parts) > 1:
                    source = parts[1].strip().split("\n")[0].strip()
                    final_answer = parts[0].strip()
            else:
                source = None  # source is optional in Task 3

            result = {
                "answer": final_answer,
                "tool_calls": tool_calls_log
            }
            if source:
                result["source"] = source
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)

    # Max iterations
    last_assistant = [m for m in messages if m["role"] == "assistant"][-1]
    final_answer = last_assistant.get("content", "No answer found after maximum iterations.") or ""
    source = None
    result = {
        "answer": final_answer,
        "tool_calls": tool_calls_log
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()