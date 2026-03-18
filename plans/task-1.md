# Task 1 Implementation Plan: Call an LLM from Code

## LLM Provider & Model
- **Provider**: OpenRouter (free tier)
- **Model**: `arcee-ai/trinity-large-preview:free`  
  (free, no credit card required, reasonable rate limits)
- **API Base**: `https://openrouter.ai/api/v1`

## Environment Configuration
- API key and endpoint will be stored in `.env.agent.secret` (not committed).
- The agent will use `python-dotenv` to load:
  - `LLM_API_KEY`
  - `LLM_API_BASE`
  - `LLM_MODEL`

## Agent Structure (`agent.py`)
1. Parse command line argument (the question).
2. Load environment variables.
3. Initialize OpenAI client with custom base URL and API key.
4. Send a chat completion request with a minimal system prompt (e.g., "You are a helpful assistant.") and the user question.
5. Extract the answer text from the response.
6. Print a JSON object with `"answer"` and `"tool_calls": []` to stdout.
7. All debug/progress information (e.g., errors, timings) goes to stderr.
8. Exit with code 0 on success, non-zero on failure.

## Testing Plan
- Write one regression test (e.g., `test_agent.py`) that runs `agent.py` with a sample question, captures stdout, parses JSON, and verifies the presence of `answer` and `tool_calls` fields.

## Dependencies
- `openai` (latest)
- `python-dotenv`
- `pytest` (for testing)

All dependencies will be managed via `uv` (or pip) as specified in the project setup.
