# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

OmniBox Wizard is a Python FastAPI service that provides AI-powered document processing and question-answering capabilities. It's part of the larger OmniBox knowledge hub system.

**Two main services:**
1. **API Server** (`omnibox_wizard/wizard/api/`) - FastAPI app with `/api/v1/wizard/ask` and `/api/v1/wizard/write` endpoints using Server-Sent Events (SSE) for streaming
2. **Worker Service** (`main.py`) - Polls the backend for document tasks (file reading, content extraction, indexing, metadata generation)

## Quick Commands

```bash
# Initialize shared modules after a fresh clone
git submodule update --init --recursive

# Install dependencies
uv sync

# Create local env file
cp example.env .env

# Development API server (port 8001)
uv run uvicorn omnibox_wizard.wizard.api.server:app --port 8001 --reload --env-file .env

# Worker service
uv run python main.py

# Production Docker build
docker build -t omnibox-wizard .

# Testing
uv run pytest                                    # Run all tests
uv run pytest tests/omnibox_wizard/test_x.py    # Run specific test file
uv run pytest -k "test_name"                    # Run tests matching pattern
uv run pytest -v                                # Verbose output
uv run pytest -s                                # Show print output

# Linting and formatting
uv run ruff check --fix                         # Lint and auto-fix
uv run ruff format                              # Format code
uv run pre-commit run --all-files               # Run pre-commit hooks
```

`compose.yaml` defines `wizard`, `wizard-worker`, and `weaviate`. The backend service is expected separately unless `OBW_BACKEND_BASE_URL` is overridden.

## Architecture

### Agent System

- **API glue** (`omnibox_wizard/wizard/api/`) - FastAPI routers and startup wiring
- **Agent implementations** (`wizard_common.grimoire.agent`) - Shared Ask/Write agents imported from the `wizard_common` submodule/package
- **Agent** - Base class for AI agents using OpenAI API
  - Handles streaming responses, tool calling (custom and standard), thinking mode
  - `UserQueryPreprocessor` transforms user queries with tool/resource context
- **Ask** - Question answering agent exposed at `/api/v1/wizard/ask`
- **Write** - Content writing agent exposed at `/api/v1/wizard/write`
- **Internal API** (`omnibox_wizard/wizard/api/internal.py`) - Search, title generation, Weaviate upsert, and capability endpoints

### Retrieval System

- **WeaviateVectorDB** (`wizard_common.grimoire.retriever.weaviate_vector_db`) - Vector search and writes via Weaviate
- **Index chunking** (`omnibox_wizard/indexing.py`, `omnibox_wizard/chunk_offsets.py`) - Resource/message chunk construction before vector writes
- **SearXNG/Reranker** - Shared grimoire tooling configured through `OBW_TOOLS_*`

### Worker Functions (`omnibox_wizard/worker/functions/`)

Each function extends `BaseFunction` and is registered in `Worker.worker_dict`:

| Function | Purpose |
|----------|---------|
| `collect` / `HTMLReaderV2` | Advanced HTML content extraction with site-specific processors |
| `collect_url` / `CollectUrlFunction` | Fetch URL HTML locally or through `OBW_TASK_SCRAPE_BASE_URL` |
| `web_analysis` / `WebAnalysisFunction` | Route URLs toward collect, video note, or audio note tasks |
| `file_reader_text` / `file_reader_ppt` / `file_reader_word` | Shared `FileReader` for multi-format file support |
| `upsert_index` | Vector index upsert to Weaviate |
| `delete_index` | Delete from vector index |
| `upsert_message_index` | Index conversation messages |
| `delete_conversation` | Delete conversation data |
| `extract_tags` / `TagExtractor` | Extract tags from content |
| `generate_title` / `TitleGenerator` | Auto-generate titles |

### HTML Reader Architecture

The `HTMLReaderV2` uses a modular processor/selector pattern:
- **Processors** (`html_reader/processors/`) - Site-specific content extractors (e.g., `red_note.py`, `okjike_web.py`)
- **Selectors** (`html_reader/selectors/`) - Site-specific CSS selectors (e.g., `zhihu_a.py`, `zhihu_q.py`)

## Configuration

All environment variables use the `OBW_` prefix. The `Loader` class from the `common` submodule/package handles loading configs from environment. Use `example.env` as the local starting point.

Key config modules:
- `WorkerConfig` (`worker/config.py`) - Worker service configuration
- `Config` (`wizard/config.py`) - API service configuration

### Function Selection

Configure enabled worker functions via `OBW_TASK_FUNCTIONS`:
```bash
# Enable all (default)
OBW_TASK_FUNCTIONS=+all

# Enable only specific functions
OBW_TASK_FUNCTIONS=-all,+collect,+file_reader_text

# Disable specific functions
OBW_TASK_FUNCTIONS=-collect
```

### Worker Counts

`main.py` starts one worker pool per function group. Tune counts with `OBW_FILE_READER_WORKER_NUM`, `OBW_INDEX_WORKER_NUM`, and `OBW_OTHER_WORKER_NUM`.

### Health Checks

- API server: `GET /api/v1/health`
- Worker health server: `GET /health` on `OBW_HEALTH_PORT` (default `8000`) when `OBW_HEALTH_ENABLED` is true
- Internal function capabilities: `GET /internal/api/v1/wizard/functions`

### Timeouts

Configure per-function timeouts via `FunctionTimeoutConfig` in `worker/config.py`. Overrides available in `OBW_TASK_FUNCTIONTIMEOUTS_*`.

## Prompt Templates

Jinja2 templates in `omnibox_wizard/resources/prompt_templates/`:
- `chat_title.j2` - Chat title generation
- `tags_extract.j2` - Tag extraction
- `html_title_extract.j2` - HTML title extraction
- `html_content_extract.j2` - HTML content extraction

The `TemplateParser` from the `common` submodule/package handles rendering.

## OpenTelemetry

Distributed tracing is configured via `common/tracing.py`:
- Automatic instrumentation for FastAPI and HTTPX
- Manual tracing with `@tracer.start_as_current_span` decorator
- Trace context propagation to backend services

## Testing

- **Framework**: pytest with `pytest-asyncio`
- **Fixtures**: `tests/omnibox_wizard/helper/fixture.py`
- **Backend mocking**: `tests/omnibox_wizard/helper/backend_mock.py`

Tests follow the pattern `tests/omnibox_wizard/test_*.py` and `tests/omnibox_wizard/*/test_*.py`.

## Tech Stack

- **Python**: 3.12+
- **Package manager**: uv
- **API**: FastAPI, Uvicorn, Pydantic
- **AI**: OpenAI API, LangChain (partial)
- **Search**: Weaviate (vector), SearXNG (web)
- **Tracing**: OpenTelemetry
- **Templates**: Jinja2
- **Testing**: pytest, pytest-asyncio
- **Linting**: Ruff

## Git Commit Guidelines

**Format**: `type(scope): Description`

**Types**:

- `feat` - New features
- `fix` - Bug fixes
- `docs` - Documentation changes
- `style` - Styling changes
- `refactor` - Code refactoring
- `perf` - Performance improvements
- `test` - Test additions or changes
- `chore` - Maintenance tasks
- `revert` - Revert previous commits
- `build` - Build system changes

**Rules**:

- Scope is required (e.g., `auth`, `resources`, `user`)
- Description in sentence case with capital first letter
- Use present tense action verbs (Add, Fix, Support, Update, Replace, Optimize)
- No period at the end
- Keep it concise and focused

**Examples**:

```
feat(auth): Support Apple signin
fix(resources): Fix tree ordering on drag-drop
chore(migrations): Add index for namespace lookup
refactor(tasks): Add timeout status handling
```

**Do NOT include**:

- "Generated with Claude Code" or similar attribution
- "Co-Authored-By: Claude" or any Claude co-author tags
