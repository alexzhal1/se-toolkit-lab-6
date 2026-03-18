#!/usr/bin/env python3
"""Agent that answers questions about a software project using tools."""

import json
import os
import sys
import io
import time
import traceback
import urllib.request
import urllib.error
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _load_env():
    for env_file in [".env", ".env.agent.secret", ".env.docker.secret"]:
        path = Path(env_file)
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            pass


_load_env()

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LMS_API_KEY = os.environ.get("LMS_API_KEY", "")
AGENT_API_BASE_URL = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002").rstrip("/")


def _safe_str(val):
    if val is None:
        return ""
    try:
        return str(val)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def read_file(path_str):
    try:
        p = Path(path_str)
        if not p.exists():
            for base in [".", "app", "src", "backend", "wiki", "docs"]:
                candidate = Path(base) / path_str
                if candidate.exists() and candidate.is_file():
                    p = candidate
                    break
            else:
                return "Error: file not found: " + str(path_str)
        if not p.is_file():
            return "Error: not a regular file: " + str(path_str)
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 30000:
            content = content[:30000] + "\n\n... [truncated]"
        return content
    except Exception as e:
        return "Error reading file: " + str(e)


def list_files(directory):
    try:
        p = Path(directory)
        if not p.exists():
            for base in [".", "src", "backend"]:
                candidate = Path(base) / directory
                if candidate.exists() and candidate.is_dir():
                    p = candidate
                    break
            else:
                root_files = []
                for item in sorted(Path(".").rglob("*")):
                    if not item.is_file():
                        continue
                    parts = item.parts
                    skip = False
                    for part in parts:
                        if part.startswith(".") or part in ("__pycache__", "node_modules", ".git"):
                            skip = True
                            break
                    if skip:
                        continue
                    root_files.append(str(item))
                    if len(root_files) >= 300:
                        break
                if root_files:
                    return ("Directory '" + directory + "' not found. "
                            "Here are all project files:\n" + "\n".join(root_files))
                return "Error: directory not found: " + directory

        files = []
        for item in sorted(p.rglob("*")):
            if not item.is_file():
                continue
            parts = item.parts
            skip = False
            for part in parts:
                if part.startswith(".") or part in ("__pycache__", "node_modules"):
                    skip = True
                    break
            if skip:
                continue
            files.append(str(item))
        if not files:
            return "No files found in " + str(directory)
        return "\n".join(files[:500])
    except Exception as e:
        return "Error listing directory: " + str(e)


def query_api(method, path_str, body="", skip_auth=False):
    """Send HTTP request with retry logic for connection failures."""
    if not path_str.startswith("/"):
        path_str = "/" + path_str

    max_retries = 3
    last_error = ""

    for attempt in range(max_retries):
        try:
            url = AGENT_API_BASE_URL + path_str
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            if not skip_auth and LMS_API_KEY:
                headers["x-api-key"] = LMS_API_KEY
                headers["Authorization"] = "Bearer " + LMS_API_KEY
            req_data = None
            if body and method.upper() in ("POST", "PUT", "PATCH"):
                req_data = body.encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers=headers, method=method.upper())

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_body = resp.read().decode("utf-8", errors="replace")
                    return json.dumps({"status_code": resp.status, "body": resp_body[:15000]})
            except urllib.error.HTTPError as e:
                resp_body = ""
                try:
                    resp_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                return json.dumps({"status_code": e.code, "body": resp_body[:15000]})
            except urllib.error.URLError as e:
                last_error = str(e.reason)
                err_lower = last_error.lower()
                if attempt < max_retries - 1 and ("refused" in err_lower or "connect" in err_lower):
                    print("Connection refused, retry " + str(attempt + 1) + "/" + str(max_retries), file=sys.stderr)
                    time.sleep(3)
                    continue
                return json.dumps({"status_code": 0, "body": "Connection error: " + last_error})
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return json.dumps({"status_code": 0, "body": "Error: " + last_error})

    return json.dumps({"status_code": 0, "body": "Connection failed after " + str(max_retries) + " retries: " + last_error})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a project file. Use for wiki (wiki/*.md), source code (*.py), "
                "config (pyproject.toml, Dockerfile, docker-compose.yml). "
                "ALWAYS use list_files first to discover paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path from project root.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in a directory recursively. Call FIRST to discover "
                "structure. Use '.' for root. Shows all project files if dir not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory: '.', 'wiki', 'app', 'src', etc.",
                    }
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": (
                "Send HTTP request to the live backend API. Use for runtime data, "
                "testing endpoints, checking status codes, reproducing errors. "
                "Auth is sent by default. Set skip_auth=true to test WITHOUT "
                "authentication. Use GET /openapi.json to discover endpoints.\n"
                "For endpoints like /items/, the response may contain a 'total' field "
                "(for paginated data) or a list. Always look for the total count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    },
                    "path": {
                        "type": "string",
                        "description": "API path, e.g. '/items/', '/openapi.json'",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON body for POST/PUT/PATCH",
                    },
                    "skip_auth": {
                        "type": "boolean",
                        "description": "If true, do NOT send auth headers.",
                    },
                },
                "required": ["method", "path"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt (улучшен)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a precise assistant that answers questions about a software project.\n"
    "You MUST use tools to gather facts. NEVER guess.\n"
    "You have ONLY three tools: read_file, list_files, query_api.\n"
    "Do NOT try to call any other tools.\n"
    "\n"
    "=== IMPORTANT: OUTPUT RULES ===\n"
    "- Do NOT output your thinking process or reasoning as your answer.\n"
    "- Do NOT start your answer with words like 'analysis', 'let me', 'we need to'.\n"
    "- Your final answer must be a DIRECT response to the question.\n"
    "- ALWAYS use tools first, THEN answer based on tool results.\n"
    "- If you have not called any tools yet, call tools first.\n"
    "\n"
    "=== FIRST: discover project structure ===\n"
    "Call list_files(\".\") FIRST to see ALL files. NEVER assume directory names.\n"
    "\n"
    "=== DECISION GUIDE ===\n"
    "\n"
    "WIKI QUESTIONS (\"according to the wiki\", \"what steps\", \"how to\",\n"
    "\"find the answer in the wiki\"):\n"
    "  1. list_files(\"wiki\") to see ALL wiki pages\n"
    "  2. Read EVERY page that could contain the answer\n"
    "  3. Read at least 3-4 pages if the first does not have the answer\n"
    "  4. NEVER say 'not found' without reading ALL wiki pages\n"
    "\n"
    "FRAMEWORK / TECH QUESTIONS (\"what framework\", \"what library\",\n"
    "\"read the source code\"):\n"
    "  1. list_files(\".\") to discover structure\n"
    "  2. read_file pyproject.toml for dependencies\n"
    "  3. read_file the main app entry point (e.g. main.py, app.py)\n"
    "  4. You MUST call read_file on at least one source file\n"
    "\n"
    "CODE STRUCTURE QUESTIONS (\"router modules\", \"domains\"):\n"
    "  1. list_files(\".\") to discover ALL files\n"
    "  2. Find and read each router/route file\n"
    "\n"
    "DATA QUESTIONS (\"how many items\", \"scores\", \"count\", \"stored in the database\"):\n"
    "  - FIRST, discover available endpoints by calling query_api('GET', '/openapi.json').\n"
    "    Look for a path like /items/, /api/items/, or similar that returns a list or total count.\n"
    "  - THEN, call that endpoint (e.g., query_api('GET', '/items/')).\n"
    "  - NEVER guess or assume the count based on init.sql or schema files – the database is populated at runtime.\n"
    "  - After calling the API, examine the response body. Look for a \"total\" field (if paginated) or count the items in the list.\n"
    "  - Output the exact number, e.g., \"There are 42 items in the database.\"\n"
    "  - Example: for \"How many items are in the database?\", you would:\n"
    "      1. query_api('GET', '/openapi.json') → find /items/\n"
    "      2. query_api('GET', '/items/') → extract total from response\n"
    "      3. answer \"There are X items.\"\n"
    "\n"
    "AUTH / STATUS CODE QUESTIONS (\"without auth\", \"unauthenticated\"):\n"
    "  1. query_api with skip_auth=true to test without auth\n"
    "  2. Report the exact HTTP status code\n"
    "  Example: \"What status code for /items/ without auth?\" → query_api('GET', '/items/', skip_auth=true)\n"
    "\n"
    "BUG DIAGNOSIS (\"crashes\", \"error\", \"what went wrong\"):\n"
    "  1. query_api to reproduce the error -- try MANY parameter values:\n"
    "     ?lab=lab-1, ?lab=lab-2, ?lab=lab-3, ?lab=lab-4, ?lab=lab-5\n"
    "  2. Read the ROUTER SOURCE CODE (not test files)\n"
    "  3. Find the exact buggy line\n"
    "  4. Report: error message + root cause + why it fails\n"
    "\n"
    "CONFIG / ARCHITECTURE QUESTIONS:\n"
    "  1. Read docker-compose.yml, Dockerfile, source code\n"
    "\n"
    "=== CRITICAL RULES ===\n"
    "1. ALWAYS use tools first. Never answer from memory.\n"
    "2. Only use: read_file, list_files, query_api. No other tools.\n"
    "3. Be precise: exact numbers, names, status codes.\n"
    "4. For wiki: read ALL pages until you find the answer.\n"
    "5. For bugs: try multiple params, read source (not tests).\n"
    "6. For count questions: your answer must be a number from the API, not from file reading.\n"
    "7. NEVER return empty. Always give a substantive answer.\n"
    "8. Your answer must DIRECTLY address the question.\n"
    "9. Always cite the source file.\n"
)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_llm(messages, tools=None):
    try:
        url = LLM_API_BASE + "/chat/completions"
        sanitized = []
        for msg in messages:
            m = dict(msg)
            if m.get("content") is None:
                m["content"] = ""
            sanitized.append(m)
        payload = {"model": LLM_MODEL, "messages": sanitized, "temperature": 0}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + LLM_API_KEY,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]
    except Exception as e:
        print("LLM error: " + str(e), file=sys.stderr)
        return None


def execute_tool(name, arguments):
    try:
        if name == "read_file":
            return read_file(_safe_str(arguments.get("path", "")))
        if name == "list_files":
            return list_files(_safe_str(arguments.get("directory", ".")))
        if name == "query_api":
            skip = arguments.get("skip_auth", False)
            if isinstance(skip, str):
                skip = skip.lower() in ("true", "1", "yes")
            return query_api(
                _safe_str(arguments.get("method", "GET")),
                _safe_str(arguments.get("path", "/")),
                _safe_str(arguments.get("body", "")),
                bool(skip),
            )
        return "Unknown tool '" + str(name) + "'. Only use: read_file, list_files, query_api."
    except Exception as e:
        return "Error executing tool: " + str(e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_source(tool_calls_log):
    wiki = []
    code = []
    other = []
    for tc in tool_calls_log:
        try:
            if not isinstance(tc, dict):
                continue
            if tc.get("tool") != "read_file":
                continue
            args = tc.get("args")
            if not isinstance(args, dict):
                continue
            path = _safe_str(args.get("path", ""))
            if not path:
                continue
            result = _safe_str(tc.get("result", ""))
            if result.startswith("Error: file not found"):
                continue
            if result.startswith("Error: not a regular file"):
                continue
            pl = path.lower()
            if "wiki" in pl or (path.endswith(".md") and "app" not in pl and "src" not in pl):
                wiki.append(path)
            elif (path.endswith(".py") or path in
                  ("pyproject.toml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml")):
                code.append(path)
            else:
                other.append(path)
        except Exception:
            continue
    if wiki:
        return wiki[-1]
    if code:
        return code[-1]
    if other:
        return other[-1]
    return ""


def _find_any_source(tool_calls_log):
    """Fallback: find any successfully read file."""
    for tc in tool_calls_log:
        if isinstance(tc, dict) and tc.get("tool") == "read_file":
            args = tc.get("args", {})
            if isinstance(args, dict) and args.get("path"):
                r = _safe_str(tc.get("result", ""))
                if not r.startswith("Error: file not found"):
                    return args["path"]
    return ""


def _is_thinking_not_answer(text):
    """Detect if text is LLM thinking/reasoning rather than a final answer."""
    if not text or len(text.strip()) < 3:
        return True
    stripped = text.strip()
    lower = stripped.lower()

    # Starts with clear thinking markers
    thinking_starts = [
        "analysis", "we need", "let's", "let me", "i need to",
        "i should", "i'll ", "i will ", "first,", "step 1",
        "my plan", "approach:", "strategy:", "thinking",
        "okay,", "ok,", "alright,", "so,", "now,",
        "to answer", "in order to", "looking at",
    ]
    for marker in thinking_starts:
        if lower.startswith(marker):
            return True

    # Starts with lowercase letter (proper answers start uppercase or with a number)
    if stripped and stripped[0].islower():
        return True

    return False


def _get_tools_used(tool_calls_log):
    """Get set of tool names actually used."""
    return {tc.get("tool") for tc in tool_calls_log if isinstance(tc, dict)}


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(question):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_calls_log = []
    max_iterations = 30
    thinking_retries = 0
    max_thinking_retries = 5  # увеличено с 3 до 5

    for iteration in range(max_iterations):
        response = call_llm(messages, TOOLS)
        if response is None:
            print("LLM returned None on iteration " + str(iteration), file=sys.stderr)
            break

        content = _safe_str(response.get("content"))
        raw_tool_calls = response.get("tool_calls")

        # --- Tool calls requested ---
        if raw_tool_calls and isinstance(raw_tool_calls, list) and len(raw_tool_calls) > 0:
            clean_tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                try:
                    if not isinstance(tc, dict):
                        continue
                    func = tc.get("function")
                    if not isinstance(func, dict):
                        continue
                    tc_id = _safe_str(tc.get("id")) or ("call_" + str(iteration) + "_" + str(i))
                    clean_tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": _safe_str(func.get("name")),
                            "arguments": _safe_str(func.get("arguments", "{}")),
                        },
                    })
                except Exception:
                    continue

            if not clean_tool_calls:
                break

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": clean_tool_calls,
            })

            for tc_clean in clean_tool_calls:
                try:
                    func = tc_clean["function"]
                    tool_name = func["name"]
                    tc_id = tc_clean["id"]
                    raw_args = func.get("arguments", "{}")
                    try:
                        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}
                    if not isinstance(tool_args, dict):
                        tool_args = {}
                    result_str = execute_tool(tool_name, tool_args)
                    tool_calls_log.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": _safe_str(result_str)[:5000],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": _safe_str(result_str),
                    })
                except Exception as e:
                    print("Tool error: " + str(e), file=sys.stderr)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_clean.get("id", "err"),
                        "content": "Error: " + str(e),
                    })
            continue

        # --- No tool calls: potential final answer ---
        answer = content.strip()

        # Check 1: Is this "thinking" output instead of a real answer?
        if _is_thinking_not_answer(answer) and thinking_retries < max_thinking_retries:
            thinking_retries += 1
            print("Detected thinking output, retry " + str(thinking_retries), file=sys.stderr)
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "That was your reasoning, not a final answer. "
                    "You MUST use tools first to gather information. "
                    "Call read_file, list_files, or query_api now. "
                    "After getting tool results, give a DIRECT answer to: "
                    + question
                ),
            })
            continue

        # Check 2: Did we actually use required tools?
        tools_used = _get_tools_used(tool_calls_log)
        q_lower = question.lower()

        # If question says "read the source code" but we never called read_file
        needs_read = ("read" in q_lower and "source" in q_lower) or "framework" in q_lower
        if needs_read and "read_file" not in tools_used and thinking_retries < max_thinking_retries:
            thinking_retries += 1
            print("Missing read_file for source code question, retry", file=sys.stderr)
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "You need to read the actual source code files to answer this. "
                    "Call list_files(\".\") to find the project structure, then "
                    "call read_file on the relevant source files (like pyproject.toml "
                    "or main.py). Then give your answer."
                ),
            })
            continue

        # If question needs API data but we never called query_api (or answer appears file-based)
        needs_api = any(kw in q_lower for kw in [
            "how many items", "query the", "status code", "endpoint",
            "stored in the database", "currently stored", "count",
        ])
        if needs_api and "query_api" not in tools_used and thinking_retries < max_thinking_retries:
            thinking_retries += 1
            print("Missing query_api for data question, retry", file=sys.stderr)
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "You need to query the live API to answer this question. "
                    "Call query_api to get the data. For example: "
                    "query_api(method=\"GET\", path=\"/items/\") or "
                    "query_api(method=\"GET\", path=\"/openapi.json\")."
                ),
            })
            continue

        # Additional check for count questions: if answer mentions init.sql or schema, force retry
        if needs_api and any(kw in q_lower for kw in ["how many items", "stored in the database"]):
            ans_lower = answer.lower()
            if "init.sql" in ans_lower or "schema" in ans_lower or "empty" in ans_lower:
                if thinking_retries < max_thinking_retries:
                    thinking_retries += 1
                    print("Answer based on init.sql instead of API, retry", file=sys.stderr)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your answer appears to be based on init.sql or schema files, "
                            "but the question asks for the current database state. "
                            "You MUST query the API to get the actual count. "
                            "Call query_api on the appropriate endpoint and extract the total number of items."
                        ),
                    })
                    continue

        # Accept the answer
        source = _extract_source(tool_calls_log)
        if not source:
            source = _find_any_source(tool_calls_log)

        return {
            "answer": answer,
            "tool_calls": tool_calls_log,
            "source": source,
        }

    # --- Max iterations or LLM error: force a final answer ---
    source = _extract_source(tool_calls_log)
    if not source:
        source = _find_any_source(tool_calls_log)

    # Если вопрос о количестве, но query_api так и не был вызван, сделаем fallback-запрос
    q_lower = question.lower()
    if any(kw in q_lower for kw in ["how many items", "stored in the database", "count"]):
        if "query_api" not in _get_tools_used(tool_calls_log):
            print("Fallback: forcing query_api to /items/", file=sys.stderr)
            fallback_result = query_api("GET", "/items/")
            tool_calls_log.append({
                "tool": "query_api",
                "args": {"method": "GET", "path": "/items/"},
                "result": fallback_result,
            })
            messages.append({
                "role": "user",
                "content": (
                    "I have called the API for you. Here is the response:\n"
                    + fallback_result + "\n"
                    "Now give your final answer based on this data."
                ),
            })
            # Попросим LLM сформировать ответ без инструментов
            final_resp = call_llm(messages, tools=None)
            if final_resp:
                final_answer = _safe_str(final_resp.get("content")).strip()
                if final_answer:
                    return {
                        "answer": final_answer,
                        "tool_calls": tool_calls_log,
                        "source": source,
                    }

    # One final LLM call without tools to force an answer
    try:
        messages.append({
            "role": "user",
            "content": (
                "Based on ALL information gathered above, give your FINAL answer "
                "to this question NOW. Do not call any tools. Answer directly:\n"
                + question
            ),
        })
        final_resp = call_llm(messages, tools=None)
        if final_resp:
            final_answer = _safe_str(final_resp.get("content")).strip()
            if final_answer and not _is_thinking_not_answer(final_answer):
                return {
                    "answer": final_answer,
                    "tool_calls": tool_calls_log,
                    "source": source,
                }
    except Exception:
        pass

    # Last resort: find any non-empty assistant message
    last_answer = ""
    for msg in reversed(messages):
        try:
            if msg.get("role") == "assistant":
                c = _safe_str(msg.get("content")).strip()
                if c and not _is_thinking_not_answer(c):
                    last_answer = c
                    break
        except Exception:
            continue

    # Absolute last resort: take any assistant content, even thinking
    if not last_answer:
        for msg in reversed(messages):
            try:
                if msg.get("role") == "assistant":
                    c = _safe_str(msg.get("content")).strip()
                    if c and len(c) > 10:
                        last_answer = c
                        break
            except Exception:
                continue

    return {
        "answer": last_answer or "Unable to determine answer.",
        "tool_calls": tool_calls_log,
        "source": source,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python agent.py <question>"}))
        sys.exit(0)

    question = sys.argv[1]
    try:
        result = run_agent(question)
    except Exception as e:
        print("Fatal: " + str(e), file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        result = {"answer": "Agent error: " + str(e), "tool_calls": [], "source": ""}

    try:
        output = json.dumps(result, ensure_ascii=True, default=str)
    except Exception:
        output = json.dumps({"answer": "JSON error", "tool_calls": [], "source": ""})
    print(output)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(json.dumps({"answer": "Fatal: " + str(e), "tool_calls": [], "source": ""}))