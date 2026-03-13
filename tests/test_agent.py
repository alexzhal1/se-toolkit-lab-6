import unittest
import subprocess
import json
import os
import sys

class TestDocumentationAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent_script = os.path.join(os.path.dirname(__file__), "agent.py")
        if not os.path.exists(cls.agent_script):
            raise FileNotFoundError(f"Agent script not found at {cls.agent_script}")

    def run_agent(self, question: str) -> dict:
        result = subprocess.run(
            [sys.executable, self.agent_script, question],
            capture_output=True,
            text=True,
            timeout=60
        )
        self.assertEqual(result.returncode, 0, f"Agent exited with non-zero code: {result.returncode}\nstderr: {result.stderr}")
        self.assertTrue(result.stdout.strip(), "stdout is empty")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout is not valid JSON: {e}\nstdout: {result.stdout}")
        return data

    def test_merge_conflict_question(self):
        data = self.run_agent("How do you resolve a merge conflict?")
        self.assertIn("answer", data)
        self.assertIn("source", data)
        self.assertIn("tool_calls", data)
        tool_names = [tc["tool"] for tc in data["tool_calls"]]
        self.assertIn("read_file", tool_names, "Agent did not call read_file")
        self.assertIn("git-workflow.md", data["source"], "Source does not point to git-workflow.md")

    def test_list_wiki_files(self):
        data = self.run_agent("What files are in the wiki?")
        self.assertIn("tool_calls", data)
        tool_names = [tc["tool"] for tc in data["tool_calls"]]
        self.assertIn("list_files", tool_names, "Agent did not call list_files")
        list_calls = [tc for tc in data["tool_calls"] if tc["tool"] == "list_files"]
        self.assertTrue(
            any("wiki" in str(tc["args"]) for tc in list_calls),
            "list_files was not called with a wiki-related path"
        )

    def test_framework_question(self):
        data = self.run_agent("What Python web framework does this project use?")
        self.assertIn("tool_calls", data)
        tool_names = [tc["tool"] for tc in data["tool_calls"]]
        self.assertIn("read_file", tool_names, "Agent did not call read_file for framework question")
        read_calls = [tc for tc in data["tool_calls"] if tc["tool"] == "read_file"]
        paths = [str(tc["args"].get("path")) for tc in read_calls]
        self.assertTrue(
            any("requirements.txt" in p or "app.py" in p for p in paths),
            "read_file was not called on a relevant file (requirements.txt or app.py)"
        )

    def test_item_count_question(self):
        data = self.run_agent("How many items are in the database?")
        self.assertIn("tool_calls", data)
        tool_names = [tc["tool"] for tc in data["tool_calls"]]
        self.assertIn("query_api", tool_names, "Agent did not call query_api for database question")
        query_calls = [tc for tc in data["tool_calls"] if tc["tool"] == "query_api"]
        paths = [str(tc["args"].get("path")) for tc in query_calls]
        self.assertTrue(
            any("/items" in p for p in paths),
            "query_api was not called with a path containing /items"
        )
        methods = [tc["args"].get("method") for tc in query_calls]
        self.assertIn("GET", methods, "query_api was not called with GET method")