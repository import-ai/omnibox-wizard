# DEVELOPER.md

This file provides guidance to developers when working with code in this repository.

## Project Overview

OmniBox Wizard is a Python FastAPI service that provides AI-powered document processing and question-answering capabilities. It's part of the larger OmniBox knowledge hub system.

**Two main services:**
1. **API Server** (`omnibox_wizard/wizard/api/`) - FastAPI app with `/api/v1/wizard/ask` and `/api/v1/wizard/write` endpoints using Server-Sent Events (SSE) for streaming
2. **Worker Service** (`main.py`) - Kafka-based consumer processing document tasks (file reading, content extraction, indexing, metadata generation)

## Quick Commands

```bash
# Install dependencies
poetry install

# Development API server (port 8001)
poetry run python -m uvicorn omnibox_wizard.wizard.api.server:app --reload --port 8001

# Worker service (with 1 worker)
poetry run python main.py --workers 1

# Production Docker build
docker build -t omnibox-wizard .

# Testing
poetry run pytest                                    # Run all tests
poetry run pytest tests/omnibox_wizard/test_x.py    # Run specific test file
poetry run pytest -k "test_name"                    # Run tests matching pattern
poetry run pytest -v                                # Verbose output
poetry run pytest -s                                # Show print output

# Linting and formatting
poetry run ruff check --fix                         # Lint and auto-fix
poetry run ruff format                              # Format code
poetry run pre-commit run --all-files              # Run pre-commit hooks
```

## Architecture

### Agent System (`omnibox_wizard/wizard/grimoire/`)

- **Agent** (`agent/agent.py`) - Base class for AI agents using OpenAI API
  - Handles streaming responses, tool calling (custom and standard), thinking mode
  - `UserQueryPreprocessor` transforms user queries with tool/resource context
- **Ask** (`agent/ask.py`) - Question answering agent
- **Write** (`agent/write.py`) - Content writing agent
- **ToolExecutor** (`agent/tool_executor.py`) - Executes tool calls from LLM responses

### Retrieval System (`omnibox_wizard/wizard/grimoire/retriever/`)

- **MeiliVectorRetriever** (`meili_vector_db.py`) - Vector search via MeiliSearch
- **SearXNG** (`searxng.py`) - Web search integration
- **Reranker** (`reranker.py`) - Post-processing reranking for improved results

### Worker Functions (`omnibox_wizard/worker/functions/`)

Each function extends `BaseFunction` and is registered in `Worker.worker_dict`:

| Function | Purpose |
|----------|---------|
| `collect` / `HTMLReaderV2` | Advanced HTML content extraction with site-specific processors |
| `file_reader` / `FileReader` | Multi-format file support (MD, Office, TXT) |
| `upsert_index` | Vector index upsert to MeiliSearch |
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

All environment variables use the `OBW_` prefix. The `Loader` class in `common/config_loader.py` handles loading configs from environment.

Key config modules:
- `WorkerConfig` (`worker/config.py`) - Worker service configuration
- `Config` (`wizard/config.py`) - API service configuration

### Function Selection

Configure enabled worker functions via `OBW_TASK_FUNCTIONS`:
```bash
# Enable all (default)
OBW_TASK_FUNCTIONS=+all

# Enable only specific functions
OBW_TASK_FUNCTIONS=-all,+collect,+file_reader

# Disable specific functions
OBW_TASK_FUNCTIONS=-collect
```

### Timeouts

Configure per-function timeouts via `FunctionTimeoutConfig` in `worker/config.py`. Overrides available in `OBW_TASK_FUNCTIONTIMEOUTS_*`.

## Prompt Templates

Jinja2 templates in `omnibox_wizard/resources/prompt_templates/`:
- `ask.j2` / `write.j2` - System prompts for agents
- `tools.j2` - Tool descriptions
- Includes support via `{% include %}` directive

The `TemplateParser` (`common/template_parser.py`) handles rendering.

## OpenTelemetry

Distributed tracing is configured via `common/tracing.py`:
- Automatic instrumentation for FastAPI and HTTPX
- Manual tracing with `@tracer.start_as_current_span` decorator
- Trace context propagation to backend services

## Testing

- **Framework**: pytest with `pytest-asyncio`
- **Testcontainers**: MeiliSearch integration via `testcontainers-compose`
- **Fixtures**: `tests/omnibox_wizard/helper/fixture.py`
- **Backend mocking**: `tests/omnibox_wizard/helper/backend_mock.py`

Tests follow the pattern `tests/omnibox_wizard/test_*.py` and `tests/omnibox_wizard/*/test_*.py`.

## Tech Stack

- **Python**: 3.12+
- **API**: FastAPI, Uvicorn, Pydantic
- **AI**: OpenAI API, LangChain (partial)
- **Search**: MeiliSearch (vector), SearXNG (web)
- **Messaging**: Kafka (aiokafka)
- **Tracing**: OpenTelemetry
- **Templates**: Jinja2
- **Testing**: pytest, testcontainers
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
