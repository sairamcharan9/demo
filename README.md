# 🔨 Forge

**Forge** is an autonomous AI software-engineering agent inspired by Google's Jules. It runs inside a sandboxed Docker container, clones a target repository, and uses a structured 5-phase workflow to understand, plan, implement, verify, and submit code changes — all driven by **Gemini 2.5 Pro** via the [Google ADK](https://google.github.io/adk-docs/).

---

## ✨ Features

- **25 built-in tools** — file I/O, shell execution, git operations, web research, planning, and user communication
- **5-phase workflow** — Orient → Plan → Execute → Verify → Submit
- **Plan-review gate** — the agent never writes code until the user approves the plan
- **Dockerised sandbox** — all file and shell access is confined to `/workspace`
- **Playwright support** — automated frontend verification out of the box
- **Memory service** — persists facts across sessions via Vertex AI / Firestore
- **Automation modes** — `NONE`, `AUTO_APPROVE`, or `AUTO_CREATE_PR`

---

## 📁 Project Structure

```
forge/
├── agent/
│   └── agent.py              # LlmAgent definition + system prompt
├── api/
│   └── __init__.py            # FastAPI service (placeholder)
├── infra/
│   └── docker/
│       └── Dockerfile         # Ubuntu 24.04 sandbox image
├── memory/
│   └── vertex_memory.py       # Session & memory services (Firestore)
├── tools/
│   ├── file_tools.py          # list, read, write, diff, delete, rename, restore
│   ├── shell_tools.py         # bash execution, frontend verification
│   ├── planning_tools.py      # set plan, review, approve, step complete
│   ├── communication_tools.py # message user, request input, submit, done
│   ├── research_tools.py      # Google Search, web scraping
│   └── git_tools.py           # commit, PR CI status
├── worker/
│   └── main.py                # Docker entry point — clone, run agent loop
├── tests/                     # pytest + pytest-asyncio test suite
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## 🚀 Getting Started

### Prerequisites

| Requirement | Purpose |
|---|---|
| **Python 3.11+** | Runtime |
| **Docker & Docker Compose** | Sandbox environment |
| **Google Cloud project** | Vertex AI, Firestore, Secret Manager |
| **GitHub token** | Clone private repos & push commits |
| **Gemini API key** | LLM inference |

### 1. Clone & configure

```bash
git clone https://github.com/<your-org>/forge.git
cd forge
cp .env.example .env
# Fill in all values in .env
```

### 2. Install dependencies (local dev)

```bash
pip install -r requirements.txt
```

### 3. Run with Docker Compose

```bash
# Set the task-specific env vars
export REPO_URL=https://github.com/owner/repo
export TASK="Add dark-mode toggle to the settings page"
export SESSION_ID=$(uuidgen)
export USER_ID=dev

docker compose up --build
```

The **worker** container will:
1. Clone the repo into `/workspace`
2. Create a Forge agent with all 25 tools
3. Run the agent loop until the task is complete

---

## 🔧 Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ✅ | GCP project ID |
| `GEMINI_API_KEY` | ✅ | Gemini API key |
| `GITHUB_TOKEN` | ✅ | GitHub PAT for clone/push |
| `REPO_URL` | ✅ | Target repository URL |
| `TASK` | ✅ | Natural-language task description |
| `SESSION_ID` | — | Unique session identifier |
| `USER_ID` | — | User identifier |
| `AUTOMATION_MODE` | — | `NONE` (default) · `AUTO_APPROVE` · `AUTO_CREATE_PR` |

---

## 🧪 Running Tests

```bash
pytest
```

The test suite covers all tool modules, the agent definition, the worker entry point, and the memory service.

---

## 🤖 How the Agent Works

```
┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐     ┌──────────┐
│  0. Orient  │ ──▶ │ 1. Plan  │ ──▶ │ 2. Execute│ ──▶ │ 3. Verify│ ──▶ │ 4. Submit│
│ list_files  │     │ set_plan │     │ write_file│     │ run tests│     │ commit   │
│ read_file   │     │ review   │     │ diff edit │     │ lint     │     │ submit   │
│ research    │     │ approval │     │ bash cmds │     │ Playwright│    │ done     │
└─────────────┘     └──────────┘     └───────────┘     └──────────┘     └──────────┘
```

> **Key rule:** The agent will *never* write code until the user approves the plan (unless `AUTOMATION_MODE` is set to `AUTO_APPROVE`).

---

## 📄 License

This project is for educational and personal use.
