# Implementation Plan

## LLM Provider Choice

I will use the Qwen Code API, which is recommended.
Model: qwen3-coder-plus.  

## Agent Structure (agent.py)

1. Load environment variables from .env.agent.secret using python-dotenv.
2. Read the question from the first command‑line argument (`sys.argv[1]`).
3. Create an OpenAI client with a custom `base_url` and `api_key`.
4. Send a chat completion request with a minimal system prompt (e.g., "You are a helpful assistant. Answer concisely.").
5. Extract the answer text from the response.
6. Print a JSON object to **stdout**.
