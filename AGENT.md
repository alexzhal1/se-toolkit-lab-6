# Agent for LLM Calls (OpenRouter)

## Overview

This is a simple CLI agent that accepts a question, sends it to an LLM via OpenRouter's OpenAI‑compatible API, and returns a structured JSON answer. It serves as the foundation for a future agent with tool‑calling capabilities.

## LLM Provider

- **Provider**: [OpenRouter](https://openrouter.ai)
- **Model**: `meta-llama/llama-3.3-70b-instruct`
- **Endpoint**: `https://openrouter.ai/api/v1`

## Configuration

All settings are stored in `.env.agent.secret`.
