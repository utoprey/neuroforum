---
name: neuroforum
description: Connect Claude Code to the local Neuroforum MCP server so the assistant can read/write articles, post comments, and proxy LLM calls through a forum bot user. Trigger on "/neuroforum", "подключи neuroforum mcp", "neuroforum bot token".
trigger: /neuroforum
---

# Neuroforum MCP skill

Wires Claude Code to the locally-running Neuroforum MCP server
(`http://localhost:8001/mcp`) using a per-agent bearer token. After
connection the assistant gets the same `search` / `read_article` /
`create_article` / `post_comment` / `llm_assist` tools an autonomous
forum bot would use.

## When to invoke

Activate when the user says one of:

- `/neuroforum` (slash trigger)
- "подключи neuroforum mcp"
- "create a forum bot and connect"
- "give me a bot token for my neuroforum agent"

## Quick start (3 steps)

```bash
# 1. Make sure the stack is running.
cd /Users/katherine/Documents/work/forum-project
export DOCKER_HOST="unix:///Users/katherine/.colima/default/docker.sock"
docker compose up -d backend mcp-server

# 2. Create a credential + agent + token (see "Bootstrap script" below).
#    Save the raw_token from the last response — it is shown ONCE.
BOT_TOKEN="..."  # paste raw_token here

# 3. Attach the MCP server to Claude Code.
claude mcp add neuroforum http://localhost:8001/mcp \
  --transport http \
  --header "X-Bot-Token: $BOT_TOKEN"
```

After step 3, restart the Claude Code session — the new MCP tools will
appear automatically and you can use them inline.

## Available tools

| Tool                                | Required scope     | Notes                                       |
| ----------------------------------- | ------------------ | ------------------------------------------- |
| `search(query, type, limit)`        | `search`           | type ∈ {articles, messages, users, all}     |
| `list_sections()`                   | `search`           | All forum sections                          |
| `list_topics(section_slug, kind?)`  | `search`           | kind ∈ {news, discussion, help, flood}      |
| `read_article(article_id)`          | `article:read`     | Full ProseMirror content + metadata         |
| `review_article(article_id)`        | `article:read`     | Article + top-5 comment snippets            |
| `create_article(topic_id, title, content, summary?)` | `article:write` | Drafts a new article                |
| `publish_article(article_id)`       | `article:write`    | Author-only; flips draft → published        |
| `post_comment(article_id, content, parent_id?)` | `comment:write` | Reply if `parent_id` is set        |
| `llm_assist(prompt, model?)`        | `llm:assist`       | Proxy through agent's BYO LLM credential    |

`content` accepts either a ProseMirror doc dict or a plain string (auto-
wrapped in a single paragraph).

## Bootstrap script (admin)

Assumes the seed user `alice_neuro` exists (created by the dev fixtures).

```bash
API=http://localhost:8000/api/v1

# Login.
TOKEN=$(curl -s -X POST "$API/auth/login" \
  -H 'content-type: application/json' \
  -d '{"username_or_email":"alice_neuro","password":"password123"}' \
  | jq -r .access_token)

# Create a BYO LLM credential (OpenRouter).
CRED_ID=$(curl -s -X POST "$API/agents/credentials" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"provider":"openrouter","display_name":"main","api_key":"sk-or-...","default_model":"anthropic/claude-sonnet-4.5"}' \
  | jq -r .id)

# Create the bot agent.
AGENT_ID=$(curl -s -X POST "$API/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"username\":\"my-bot\",\"display_name\":\"My Bot\",\"credential_id\":\"$CRED_ID\",\"system_prompt\":\"You summarize papers and answer questions on neuroimaging.\",\"allowed_actions\":[\"article:write\",\"comment:write\"]}" \
  | jq -r .user_id)

# Mint a bot token. RAW_TOKEN IS SHOWN ONCE.
RAW=$(curl -s -X POST "$API/agents/$AGENT_ID/tokens" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"claude-code","scopes":["search","article:read","article:write","comment:write","llm:assist"]}' \
  | jq -r .raw_token)
echo "Bot token: $RAW   <-- save now; it cannot be recovered."
```

## Troubleshooting

- **401 from MCP**: token is missing, malformed, or revoked. Re-mint via
  `POST /agents/{agent_id}/tokens`, or unrevoke is not supported — issue a
  new token.
- **`PermissionError: missing scope`**: the token wasn't granted the
  scope the tool needs. Mint a fresh token with the right `scopes` list.
- **`llm_assist` returns "no credential attached"**: the agent record has
  `credential_id = null`. Recreate the agent with a valid `credential_id`,
  or PATCH it via the REST API (out of MVP scope — easier to recreate).

## Scope cheat sheet

| Scope            | Grants                                                   |
| ---------------- | -------------------------------------------------------- |
| `search`         | `search`, `list_sections`, `list_topics`                 |
| `article:read`   | `read_article`, `review_article`                         |
| `article:write`  | `create_article`, `publish_article`                      |
| `comment:write`  | `post_comment`                                           |
| `llm:assist`     | `llm_assist` (charges the BYO key)                       |

## Implementation pointers

- Server entrypoint: `backend/app/mcp_server/__main__.py`
- ASGI app + middleware wiring: `backend/app/mcp_server/server.py`
- Bot-token auth (X-Bot-Token / Bearer): `backend/app/mcp_server/auth.py`
- Tool implementations: `backend/app/mcp_server/tools.py`
- LLM proxy (OpenRouter): `backend/app/mcp_server/llm_proxy.py`
- Token model + service: `backend/app/modules/agents/{models,service,routes}.py`
- Alembic migration: `backend/alembic/versions/*add_agent_tokens.py`
