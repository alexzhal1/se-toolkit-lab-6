#!/usr/bin/env python3
"""Regression tests for the system agent's tool-calling behaviour.

Run with:
    uv run pytest tests/test_system_agent.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _load_env():
    """Load .env files so tests can check for credentials."""
    for env_file in [".env", ".env.agent.secret", ".env.docker.secret"]:
        path = Path(env_file)
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
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

HAS_LLM = bool(os.environ.get("LLM_API_KEY"))
SKIP_REASON = "LLM credentials not configured (set LLM_API_KEY)"


def _run_agent(question: str, timeout: int = 120) -> dict:
    """Run agent.py as a subprocess and return the parsed JSON output."""
    result = subprocess.run(
        [sys.executable, "agent.py", question],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"agent.py exited with code {result.returncode}\n"
        f"stderr: {result.stderr[:500]}"
    )
    stdout = result.stdout.strip()
    assert stdout, "agent.py produced no output"
    data = json.loads(stdout)
    assert "answer" in data, f"Missing 'answer' field: {stdout[:200]}"
    return data


def _tools_used(data: dict) -> set:
    """Extract the set of tool names used from agent output."""
    return {
        tc.get("tool")
        for tc in data.get("tool_calls", [])
        if isinstance(tc, dict)
    }


def _query_api_calls_with_skip_auth(data: dict) -> bool:
    """Check if any query_api call had skip_auth=true."""
    for tc in data.get("tool_calls", []):
        if tc.get("tool") == "query_api":
            args = tc.get("args", {})
            skip = args.get("skip_auth")
            if skip in [True, "true"]:
                return True
    return False


@pytest.mark.skipif(not HAS_LLM, reason=SKIP_REASON)
def test_framework_question_uses_read_file():
    """Asking about the backend framework should trigger read_file."""
    data = _run_agent("What Python web framework does this project use?")
    tools = _tools_used(data)

    assert "read_file" in tools, (
        f"Expected 'read_file' in tool_calls, but agent used: {tools}"
    )
    answer_lower = data.get("answer", "").lower()
    assert any(
        kw in answer_lower
        for kw in ["fastapi", "flask", "django", "starlette", "litestar"]
    ), f"Answer doesn't mention a known framework: {data['answer'][:200]}"

    assert "source" in data, "Expected a 'source' field"


@pytest.mark.skipif(not HAS_LLM, reason=SKIP_REASON)
def test_item_count_uses_query_api():
    """Asking about database item count should trigger query_api."""
    data = _run_agent("How many items are in the database?")
    tools = _tools_used(data)

    assert "query_api" in tools, (
        f"Expected 'query_api' in tool_calls, but agent used: {tools}"
    )
    numbers = re.findall(r"\d+", data.get("answer", ""))
    assert numbers, f"Answer doesn't contain any numbers: {data['answer'][:200]}"


@pytest.mark.skipif(not HAS_LLM, reason=SKIP_REASON)
def test_unauthorized_status_code_uses_query_api_with_skip_auth():
    """Question about unauthorized access should use query_api with skip_auth=true."""
    data = _run_agent("What HTTP status code does the API return when calling /items/ without authentication?")
    tools = _tools_used(data)

    assert "query_api" in tools, (
        f"Expected 'query_api' in tool_calls, but agent used: {tools}"
    )
    # Проверяем, что хотя бы один вызов query_api имел skip_auth=true
    assert _query_api_calls_with_skip_auth(data), (
        "No query_api call with skip_auth=true found in tool_calls"
    )
    answer_lower = data.get("answer", "").lower()
    assert any(str(code) in answer_lower for code in [401, 403]), (
        f"Answer doesn't mention 401 or 403: {data['answer'][:200]}"
    )


@pytest.mark.skipif(not HAS_LLM, reason=SKIP_REASON)
def test_database_schema_uses_read_file():
    """Question about database schema should trigger read_file."""
    data = _run_agent("What is the database schema? Look in the source code.")
    tools = _tools_used(data)

    assert "read_file" in tools, (
        f"Expected 'read_file' in tool_calls, but agent used: {tools}"
    )
    answer_lower = data.get("answer", "").lower()
    assert any(kw in answer_lower for kw in ["table", "column", "schema", "sql"]), (
        f"Answer doesn't mention schema-related terms: {data['answer'][:200]}"
    )
    assert "source" in data, "Expected a 'source' field"