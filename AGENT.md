# Agent Documentation

## Overview
`agent.py` is a simple command-line interface that forwards a user question to a Large Language Model (LLM) and returns a structured JSON response. It serves as the foundation for a more advanced agent that will include tool calling and an agentic loop in later tasks.

## Architecture
- The agent reads configuration from a `.env.agent.secret` file (not committed to version control).
- It uses the OpenAI Python library to communicate with any OpenAI‑compatible API (here, OpenRouter).
- The agent prints **only** a valid JSON object to stdout; all other output (debug, errors) goes to stderr.
- On success, it exits with code 0; on failure, it exits with a non‑zero code.

## LLM Provider
- **Provider**: OpenRouter (free tier)
- **Model**: `arcee-ai/trinity-large-preview:free`
- **API Base**: `https://openrouter.ai/api/v1`

The free model has a rate limit of 50 requests per day per account, which is sufficient for development and testing with the provided evaluation script (if run one question at a time).

## Configuration
Create a `.env.agent.secret` file in the project root with the following variables:
