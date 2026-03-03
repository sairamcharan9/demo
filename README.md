# 🔨 Forge

**Forge** is an autonomous AI software-engineering agent inspired by [Google Jules](https://jules.google.com/). It runs as a local sandboxed agent, clones a target repository, and uses a structured 5-phase workflow to understand, plan, implement, verify, and submit code changes — all driven by **Gemini 2.5 Pro** via the [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/).

---

## ✨ Features

- **32 built-in tools** — file I/O, shell execution, git operations, web research, planning, and user communication
- **5-phase workflow** — Orient → Plan → Execute → Verify → Submit
- **Plan-review gate** — the agent never writes code until the user approves the plan
- **Auto-branch creation** — feature branches are automatically created once the plan is approved
- **Local sandbox** — all file and shell access is confined to the `workspace/` directory
- **Playwright support** — automated frontend verification with headless Chromium screenshots
- **Memory service** — persists discovered facts across sessions via Vertex AI Memory Bank
- **Session persistence** — dual-mode (InMemory for dev, VertexAI/Firestore for prod)
- **Automation modes** — `NONE`, `AUTO_APPROVE`, or `AUTO_CREATE_PR`
- **AG-UI ready** — designed for integration with [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui) and CopilotKit
- **Rate-limit retry** — exponential backoff on Gemini API rate limits

---

## 📁 Project Structure

```
forge/
├── agent/
│   └── agent.py              # LlmAgent definition + system prompt + callbacks
├── api/
│   └── __init__.py            # FastAPI service (Week 4 — placeholder)
├── workspace/                 # Local verification workspace
├── memory/
│   └── vertex_memory.py       # Session & memory services (InMemory / VertexAI)
├── tools/
│   ├── file_tools.py          # 8 tools: list, read, write, diff, delete, rename, restore, reset
│   ├── shell_tools.py         # 3 tools: bash execution, frontend verification
│   ├── planning_tools.py      # 6 tools: plan lifecycle, memory recording
│   ├── communication_tools.py # 7 tools: messaging, submit, done, PR comments
│   ├── research_tools.py      # 4 tools: Google Search, web scraping, screenshots
│   └── git_tools.py           # 4 tools: commit, branch, PR, CI status
├── worker/
│   └── main.py                # Worker entry point — clone, run agent loop
├── tests/                     # 172 tests — pytest + pytest-asyncio
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## 🛠️ Tool Reference (32 Tools)

### File Tools (8)
| Tool | Purpose |
|---|---|
| `list_files` | List all files in a directory tree |
| `read_file` | Read file content with line numbers |
| `write_file` | Create or overwrite a file |
| `replace_with_git_merge_diff` | Apply a unified diff via `git apply` |
| `delete_file` | Delete a file or directory |
| `rename_file` | Move or rename a file |
| `restore_file` | Revert a file to last committed state |
| `reset_all` | Hard reset workspace to HEAD |

### Shell Tools (3)
| Tool | Purpose |
|---|---|
| `run_in_bash_session` | Execute bash command with timeout |
| `frontend_verification_instructions` | Return Playwright test instructions |
| `frontend_verification_complete` | Read and return verification screenshots |

### Planning Tools (6)
| Tool | Purpose |
|---|---|
| `set_plan` | Write execution plan to session state |
| `plan_step_complete` | Mark a step as done, advance to next |
| `request_plan_review` | Pause and wait for user approval |
| `record_user_approval_for_plan` | Record plan approval |
| `pre_commit_instructions` | Return pre-submit checklist |
| `initiate_memory_recording` | Persist a discovered fact |

### Communication Tools (7)
| Tool | Purpose |
|---|---|
| `message_user` | Send a status message |
| `request_user_input` | Ask a question, wait for response |
| `send_message_to_user` | Typed message (progress/warning/error) |
| `submit` | Full git submission flow (commit + push + PR) |
| `done` | Signal task completion |
| `read_pr_comments` | Fetch PR review comments |
| `reply_to_pr_comments` | Post a comment on a PR |

### Research Tools (4)
| Tool | Purpose |
|---|---|
| `google_search` | Search via Google Custom Search API |
| `view_text_website` | Fetch URL and extract readable text |
| `take_screenshot` | Capture URL screenshot via Playwright |
| `view_image` | Read image file and return base64 |

### Git Tools (4)
| Tool | Purpose |
|---|---|
| `make_commit` | Stage all + commit with message |
| `create_branch` | Create and switch to new branch |
| `create_pr` | Create GitHub PR via `gh` CLI |
| `watch_pr_ci_status` | Check CI status for a PR |

---

## 🚀 Getting Started

### Prerequisites

| Requirement | Purpose |
|---|---|
| **Python 3.11+** | Runtime |
| **Git & gh CLI** | Version control & PRs |
| **Google Cloud project** | Vertex AI, Firestore (prod mode only) |
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

### 3. Run tests

```bash
python -m pytest tests/ --ignore=tests/test_e2e_agent.py -v
```

### 4. Run worker loop

```bash
export REPO_URL=https://github.com/owner/repo
export TASK="Add dark-mode toggle to the settings page"
export SESSION_ID=$(uuidgen)
export USER_ID=dev

python -m worker.main
```

The **worker** will:
1. Clone the repo into `WORKSPACE_ROOT/workspace`
2. Create a Forge agent with all 32 tools
3. Run the 5-phase agent loop until the task is complete

---

## 🔧 Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ | Gemini API key |
| `GEMINI_MODEL` | — | Model name (default: `gemini-2.5-pro`) |
| `REPO_URL` | ✅ | Target repository URL |
| `TASK` | ✅ | Natural-language task description |
| `GITHUB_TOKEN` | ✅ | GitHub PAT for clone/push |
| `SESSION_ID` | — | Unique session identifier |
| `USER_ID` | — | User identifier |
| `AUTOMATION_MODE` | — | `NONE` (default) · `AUTO_APPROVE` · `AUTO_CREATE_PR` |
| `SERVICE_MODE` | — | `dev` (InMemory) or `prod` (VertexAI/Firestore) |
| `GOOGLE_CLOUD_PROJECT` | Prod | GCP project ID |
| `WORKSPACE_ROOT` | — | Workspace path (default: `/workspace`) |

---

## 🤖 How the Agent Works

```
┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐     ┌──────────┐
│  0. Orient  │ ──▶ │ 1. Plan  │ ──▶ │ 2. Execute│ ──▶ │ 3. Verify│ ──▶ │ 4. Submit│
│ list_files  │     │ set_plan │     │ write_file│     │ run tests│     │ commit   │
│ read_file   │     │ review   │     │ diff edit │     │ lint     │     │ create_pr│
│ research    │     │ approval │     │ bash cmds │     │ Playwright│    │ submit   │
│ memory rec  │     │ branch   │     │ step done │     │ frontend │     │ done     │
└─────────────┘     └──────────┘     └───────────┘     └──────────┘     └──────────┘
```

**Key rules:**
- The agent **never** writes code until the plan is approved (unless `AUTOMATION_MODE=AUTO_APPROVE`)
- Feature branches are **auto-created** when execution begins
- The agent **never** submits code that fails tests

---

## 📈 MVP Build Progress

| Week | Gate | Status |
|---|---|---|
| **Week 1** | Sandbox Verified — local workspace, all file/shell/planning tools tested | ✅ Complete |
| **Week 2** | Agent Verified Locally — full 5-phase flow with InMemorySessionService | ✅ Complete |
| **Week 3** | Persistence Verified — VertexAI session/memory with container restart | ⬜ Not started |
| **Week 4** | API + AG-UI Complete — FastAPI endpoints, CopilotKit integration | ⬜ Not started |
| **Week 5** | GitHub Integration Complete — real PRs, CI fixer loop | ⬜ Not started |
| **Week 6+** | Frontend — CopilotKit React UI | ⬜ Not started |

---

## 🧪 Test Coverage

| Module | Tests | Coverage | Status |
|---|---|---|---|
| `file_tools.py` | 23 tests | 77% | ✅ Pass |
| `shell_tools.py` | 12 tests | 84% | ✅ Pass |
| `planning_tools.py` | 22 tests | 98% | ✅ Pass |
| `communication_tools.py` | 34 tests | 84% | ✅ Pass |
| `research_tools.py` | 23 tests | 85% | ✅ Pass |
| `git_tools.py` | 20 tests | 81% | ✅ Pass |
| `memory/vertex_memory.py` | 8 tests | 92% | ✅ Pass |
| `agent/agent.py` | 23 tests | 73% | ✅ Pass |
| `worker/main.py` | 7 tests | 70% | ✅ Pass |
| **Total** | **172 tests** | **81%** | **✅ Pass** |

---

## 🔌 ADK Compatibility

Fully compatible with Google ADK:
- Uses `LlmAgent` with `instruction`, `tools`, `before_model_callback`, `after_tool_callback`
- Session state injection via `{key}` placeholders in system prompt
- `ToolContext.state` for all state mutations
- Dual-mode memory/session services (InMemory / VertexAI)
- `Runner.run_async()` event loop with proper Content/Part types

---

## 📄 License

This project is for educational and personal use.
