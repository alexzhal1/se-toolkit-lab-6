
import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load configuration from .env.agent.secret
load_dotenv(".env.agent.secret")

LLM_API_BASE = os.getenv("LLM_API_BASE")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")

# Validate required variables
if not LLM_API_BASE or not LLM_API_KEY or not LLM_MODEL:
    print(
        "Error: LLM_API_BASE, LLM_API_KEY, and LLM_MODEL must be set in .env.agent.secret",
        file=sys.stderr
    )
    sys.exit(1)


def call_llm(question: str) -> str:
    """Send the question to the LLM via OpenRouter and return the answer text."""
    client = OpenAI(
        base_url=LLM_API_BASE,
        api_key=LLM_API_KEY,
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                {"role": "user", "content": question}
            ],
            temperature=0.0,
            timeout=30  # seconds
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"LLM call failed: {e}", file=sys.stderr)
        sys.exit(1)

if len(sys.argv) != 2:
    print("Usage: agent.py <question>", file=sys.stderr)
    sys.exit(1)

question = sys.argv[1]
answer = call_llm(question)

# Build the required JSON output
result = {
    "answer": answer,
    "tool_calls": []   # empty for now (will be used in Task 2)
}

# Only the JSON goes to stdout
print(json.dumps(result, ensure_ascii=False))
sys.exit(0)