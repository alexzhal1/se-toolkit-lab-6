# Task 3: The System Agent – Implementation Plan

## Overview
In this task, we extend the documentation agent from Task 2 with a new tool `query_api` that allows it to interact with the deployed backend. The agent will now answer both static system questions (framework, ports, status codes) and dynamic data queries (item count, scores) by calling the backend API.

## New Tool: `query_api`
- **Purpose**: Send HTTP requests to the backend API.
- **Parameters**:
  - `method` (string): HTTP method (GET, POST, etc.)
  - `path` (string): API endpoint path (e.g., `/items/`)
  - `body` (string, optional): JSON request body for POST/PUT requests.
- **Returns**: JSON string with `status_code` and `body` (the response body).
- **Authentication**: The tool adds an `Authorization: Bearer <LMS_API_KEY>` header using the key from the environment variable `LMS_API_KEY`.
- **Base URL**: Read from `AGENT_API_BASE_URL` environment variable, defaulting to `http://localhost:42002`.

## Environment Variables
The agent must read all configuration from environment variables:
- `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL` – for LLM access (from `.env.agent.secret`).
- `LMS_API_KEY` – for backend authentication (from `.env.docker.secret`).
- `AGENT_API_BASE_URL` – backend base URL (default: `http://localhost:42002`).

## System Prompt Update
The system prompt will be extended to explain when to use `query_api`:
- Use `list_files` and `read_file` for documentation or source code questions.
- Use `query_api` for questions about live system data (e.g., item counts, scores) or API behaviour.
- The agent may need to chain tools: e.g., first query an API endpoint, then read source code to debug an error.

## Agentic Loop
The loop remains the same as Task 2 (max 10 iterations). The new tool is just another function the LLM can call.

## Benchmark Strategy
I will run `run_eval.py` locally to identify failing questions. Based on the feedback, I will:
- Refine tool descriptions if the LLM misuses them.
- Adjust the system prompt to guide the LLM towards the correct tool for each question type.
- Fix any bugs in the tool implementation (e.g., handling of query parameters, error responses).
- Increase the content limit for file reads if the LLM gets stuck in loops.

Initial benchmark run (hypothetical):
- 6/10 passed.
- Failures on questions requiring chaining (e.g., API error then code lookup).
- Iteration plan: improve prompt to encourage chaining, and ensure error messages from `query_api` are informative.

## Testing
Two new regression tests will be added:
- `"What Python web framework does this project use?"` – expects `read_file` to be called (looking at code).
- `"How many items are in the database?"` – expects `query_api` to be called with `GET /items/`.

These will be added to `test_agent.py`.