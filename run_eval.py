#!/usr/bin/env python3
"""Local evaluation runner for the agent benchmark.

Fetches questions one at a time from the autochecker API,
runs your agent, and checks the answer locally.

Usage:
    uv run run_eval.py           # all questions, run ALL (don't stop on fail)
    uv run run_eval.py --index 5 # single question (for debugging)

Reads from .env (same credentials as the autochecker):
    AUTOCHECKER_API_URL
    AUTOCHECKER_EMAIL
    AUTOCHECKER_PASSWORD
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _load_env():
    """Load variables from .env file (simple key=value parser)."""
    for env_file in [".env", ".env.docker.secret"]:
        path = Path(env_file)
        if not path.exists():
            continue
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


def _get_credentials():
    """Return (api_url, email, password) from environment."""
    api_url = os.environ.get("AUTOCHECKER_API_URL", "")
    email = os.environ.get("AUTOCHECKER_EMAIL", "")
    password = os.environ.get("AUTOCHECKER_PASSWORD", "")
    if not all([api_url, email, password]):
        print(
            "Missing credentials. Set AUTOCHECKER_API_URL, AUTOCHECKER_EMAIL, "
            "and AUTOCHECKER_PASSWORD in your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_url.rstrip("/"), email, password


def _basic_auth_header(email: str, password: str) -> str:
    """Build HTTP Basic Auth header value."""
    encoded = base64.b64encode(f"{email}:{password}".encode()).decode()
    return f"Basic {encoded}"


def _fetch_question(api_url: str, auth: str, lab: str, index: int):
    """Fetch a question from the autochecker API. Returns dict or None on 404."""
    import urllib.request
    import urllib.error

    url = f"{api_url}/api/eval/question?lab={lab}&index={index}"
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body = e.read().decode() if e.fp else ""
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach API: {e.reason}", file=sys.stderr)
        sys.exit(1)


def _run_agent(question: str, timeout: int = 240):
    """Run agent.py with the question. Returns (answer_dict, error_msg)."""
    try:
        result = subprocess.run(
            [sys.executable, "agent.py", question],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "Agent timed out (120s)"
    except FileNotFoundError:
        return None, "agent.py not found"

    if result.returncode != 0:
        stderr_preview = result.stderr.strip()[:200] if result.stderr else ""
        return None, f"Agent exited with code {result.returncode}: {stderr_preview}"

    stdout = result.stdout.strip()
    if not stdout:
        return None, "Agent produced no output"

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, f"Agent output is not valid JSON: {stdout[:200]}"

    if "answer" not in data:
        return None, f"Missing 'answer' field in output: {stdout[:200]}"

    return data, None


# ---------------------------------------------------------------------------
# Matching logic (mirrors autochecker evaluation)
# ---------------------------------------------------------------------------

def _try_float(s):
    """Try to convert string to float, return None on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _match(text: str, rule: dict) -> bool:
    """Check if text satisfies the matching rule."""
    text_lower = text.lower()

    if "contains" in rule:
        return rule["contains"].lower() in text_lower

    if "contains_all" in rule:
        return all(kw.lower() in text_lower for kw in rule["contains_all"])

    if "any_of" in rule:
        return any(kw.lower() in text_lower for kw in rule["any_of"])

    if "regex" in rule:
        return bool(re.search(rule["regex"], text, re.IGNORECASE))

    if "numeric_gt" in rule:
        numbers = re.findall(r"\d+\.?\d*", text)
        for n in numbers:
            val = _try_float(n)
            if val is not None and val > rule["numeric_gt"]:
                return True
        return False

    if "numeric_range" in rule:
        lo, hi = rule["numeric_range"]
        numbers = re.findall(r"\d+\.?\d*", text)
        for n in numbers:
            val = _try_float(n)
            if val is not None and lo <= val <= hi:
                return True
        return False

    return False


def _format_expected(expected: dict) -> str:
    """Human-readable description of the expected match."""
    if "contains" in expected:
        return f"answer should contain: \"{expected['contains']}\""
    if "contains_all" in expected:
        return f"answer should contain all of: {expected['contains_all']}"
    if "any_of" in expected:
        return f"answer should contain any of: {expected['any_of']}"
    if "regex" in expected:
        return f"answer should match pattern: {expected['regex']}"
    if "numeric_gt" in expected:
        return f"answer should contain a number > {expected['numeric_gt']}"
    if "numeric_range" in expected:
        return f"answer should contain a number in range {expected['numeric_range']}"
    return str(expected)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

LAB = "lab-06"


def _check_question(q: dict, data: dict) -> tuple[bool, str]:
    """Check agent output against question expectations.

    Returns (passed, failure_reason). failure_reason is empty on pass.
    Checks: (1) answer keywords, (2) source reference, (3) tool usage.
    """
    answer = data.get("answer", "")
    expected = q.get("expected", {})

    # Check answer
    if expected:
        if not _match(answer, expected):
            feedback = q.get("feedback")
            if feedback:
                return False, f"    {YELLOW}hint: {feedback}{RESET}"
            else:
                return False, f"    Expected: {_format_expected(expected)}"
    elif q.get("has_rubric"):
        if len(answer.split()) < 20:
            return False, f"    {YELLOW}Answer too short for a reasoning question (bot uses LLM judge){RESET}"

    # Check source if expected_source is defined
    expected_source = q.get("expected_source")
    if expected_source:
        source = data.get("source", "")
        if not source:
            return False, f"    Missing 'source' field (expected a file reference)"
        if not _match(source, expected_source):
            feedback = q.get("feedback")
            if feedback:
                return False, f"    {YELLOW}hint: {feedback}{RESET}"
            else:
                return False, f"    Source '{source}' doesn't match expected"

    # Check tool usage
    check_tools = q.get("check_tools")
    if check_tools:
        tool_calls = data.get("tool_calls", [])
        tools_used = {tc.get("tool") for tc in tool_calls} if tool_calls else set()
        missing = set(check_tools) - tools_used
        if missing:
            return False, (
                f"    Expected tool calls: {', '.join(check_tools)}\n"
                f"    Missing: {', '.join(missing)}\n"
                f"    Your agent used: {', '.join(tools_used) or '(none)'}"
            )

    return True, ""


def main():
    parser = argparse.ArgumentParser(description="Run agent evaluation benchmark")
    parser.add_argument(
        "--index", type=int, default=None,
        help="Run a single question by index (for debugging)"
    )
    args = parser.parse_args()

    _load_env()
    api_url, email, password = _get_credentials()
    auth = _basic_auth_header(email, password)

    if args.index is not None:
        # Single question mode
        q = _fetch_question(api_url, auth, LAB, args.index)
        if q is None:
            print(f"Question {args.index} not found", file=sys.stderr)
            sys.exit(1)

        try:
            Path("last_question_debug.json").write_text(
                json.dumps(q, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

        question = q["question"]
        print(f"  [{args.index}] {question}")

        data, error = _run_agent(question)
        if error:
            print(f"  {RED}Error: {error}{RESET}")
            sys.exit(1)

        passed_q, reason = _check_question(q, data)
        answer = data.get("answer", "")
        source = data.get("source", "")
        tool_calls = data.get("tool_calls", [])

        print(f"  Answer: {answer[:200]}")
        if source:
            print(f"  Source: {source}")
        if tool_calls:
            tools_used = [tc.get("tool", "?") for tc in tool_calls]
            print(f"  Tools: {', '.join(tools_used)}")

        if passed_q:
            print(f"  {GREEN}PASSED{RESET}")
        else:
            print(f"  {RED}FAILED{RESET}")
            print(reason)
            sys.exit(1)
        return

    # Full run mode -- run ALL questions, don't stop on failure
    index = 0
    passed = 0
    failed = 0
    total = 0
    failures = []

    while True:
        q = _fetch_question(api_url, auth, LAB, index)
        if q is None:
            break

        total = q["total"]
        question = q["question"]

        data, error = _run_agent(question)

        if error:
            print(f"  {RED}x [{index + 1}/{total}] {question}{RESET}")
            print(f"    Error: {error}")
            failed += 1
            failures.append({
                "index": index,
                "question": question,
                "error": error,
            })
            index += 1
            continue

        ok, reason = _check_question(q, data)

        if ok:
            print(f"  {GREEN}+ [{index + 1}/{total}] {question}{RESET}")
            passed += 1
        else:
            answer = data.get("answer", "")
            source = data.get("source", "")
            tool_calls = data.get("tool_calls", [])
            print(f"  {RED}x [{index + 1}/{total}] {question}{RESET}")
            print(f"    Your answer: {answer[:200]}")
            if source:
                print(f"    Source: {source}")
            if tool_calls:
                tools_used = [tc.get("tool", "?") for tc in tool_calls]
                print(f"    Tools: {', '.join(tools_used)}")
            print(reason)
            failed += 1
            failures.append({
                "index": index,
                "question": question,
                "answer": answer[:200],
                "reason": reason,
            })

        index += 1

    # Summary
    total_run = passed + failed
    if total_run == 0:
        print(f"\n{YELLOW}No questions found.{RESET}")
        return

    if failed == 0:
        print(f"\n{BOLD}{GREEN}{passed}/{total_run} PASSED -- ALL CLEAR!{RESET}")
    else:
        print(f"\n{BOLD}{passed}/{total_run} passed, {RED}{failed} failed{RESET}")
        print(f"\n{YELLOW}Failed questions:{RESET}")
        for f in failures:
            print(f"  [{f['index'] + 1}] {f['question']}")
            if "error" in f:
                print(f"      Error: {f['error'][:100]}")
            if "answer" in f:
                print(f"      Answer: {f.get('answer', '')[:100]}")

    print(
        f"\n{YELLOW}Note: The autochecker bot tests additional hidden questions"
        f" and may use LLM-based judging for open-ended answers."
        f" You need to pass a minimum threshold overall.{RESET}"
    )

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()