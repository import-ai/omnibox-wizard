"""
Product Documentation Handler

Fetches official OmniBox product documentation from GitHub repository
and returns full content based on user's language preference.
"""

import asyncio
import base64

import httpx
from opentelemetry import trace

from omnibox_wizard.wizard.grimoire.entity.tools import BaseTool
from omnibox_wizard.wizard.grimoire.entity.resource import ResourceToolResult, ResourceInfo
from omnibox_wizard.wizard.grimoire.retriever.resource import BaseResourceHandler, ResourceFunction

GITHUB_API = "https://api.github.com"
OWNER = "import-ai"
REPO = "omnibox-docs"

tracer = trace.get_tracer(__name__)


class ProductDocsHandler(BaseResourceHandler):
    """Handler for product_docs tool.

    Product docs is always available (unlike other resource tools that require private_search),
    and it doesn't go through the reranker since it returns fixed content.
    """

    def __init__(self, github_token: str | None = None):
        self.github_token = github_token
        self._cache: dict[str, str] = {"zh": "", "en": ""}
        self._initialized = False

    async def _fetch_all(self, path: str) -> str:
        """Recursively fetch all .md files from a directory and combine."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        contents = []

        async def fetch(client, repo_path):
            try:
                resp = await client.get(
                    f"/repos/{OWNER}/{REPO}/contents/{repo_path}",
                    headers=headers
                )
                resp.raise_for_status()
                items = resp.json()

                for item in items:
                    if item.get("type") == "file" and item["name"].endswith(".md"):
                        f = await client.get(
                            f"/repos/{OWNER}/{REPO}/contents/{item['path']}",
                            headers=headers
                        )
                        f.raise_for_status()
                        content = base64.b64decode(f.json()["content"]).decode("utf-8")
                        contents.append(f"\n\n# {item['name']}\n\n{content}")
                    elif item.get("type") == "dir":
                        await fetch(client, item["path"])
            except Exception as e:
                tracer.get_current_span().record_exception(e)

        async with httpx.AsyncClient(base_url=GITHUB_API, timeout=30.0) as client:
            await fetch(client, path)
        return "\n".join(contents)

    async def _ensure_init(self):
        """Initialize cache by fetching both language versions in parallel."""
        if self._initialized:
            return
        zh, en = await asyncio.gather(
            self._fetch_all("docs/zh-cn"),
            self._fetch_all("docs/en"),
        )
        self._cache["zh"] = zh
        self._cache["en"] = en
        self._initialized = True

    def get_function(self, tool: BaseTool, **kwargs) -> ResourceFunction:
        """Return a function that fetches product docs and returns ResourceToolResult."""
        lang = kwargs.get("lang", "简体中文")

        async def _product_docs() -> ResourceToolResult:
            await self._ensure_init()
            lang_key = "zh" if lang == "简体中文" else "en"
            content = self._cache.get(lang_key, "")

            if content:
                return ResourceToolResult(
                    success=True,
                    data=ResourceInfo(
                        id="product_docs",
                        name="OmniBox Product Documentation",
                        resource_type="doc",
                        content=content,
                        updated_at=None,
                    ),
                )
            return ResourceToolResult(
                success=False,
                error="Failed to fetch product documentation."
            )

        return _product_docs

    @classmethod
    def get_schema(cls) -> dict:
        """Return the tool schema for product_docs."""
        return {
            "type": "function",
            "function": {
                "name": "product_docs",
                "display_name": {"zh": "查询产品文档", "en": "Search Product Docs"},
                "description": (
                    "Get official OmniBox product documentation (pricing, features, plugins, usage). "
                    "Use this tool when users ask questions about the product itself. "
                    "This tool requires NO parameters - call it with empty arguments: {}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    @property
    def name(self) -> str:
        return self.get_schema()["function"]["name"]
