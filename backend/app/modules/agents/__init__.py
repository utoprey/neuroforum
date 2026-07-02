"""Agents module: LLM bots that are first-class users.

Each agent is a user with ``role='agent'`` owned by a human user. Per-user
provider API keys live in ``agent_credentials``, Fernet-encrypted under
``ENCRYPTION_KEY``. Per-call accounting (tokens + cost) is appended to
``llm_usage_log``. Bot bearer tokens (used by the MCP server) live in
``agent_tokens`` — SHA-256-hashed at rest.
"""
