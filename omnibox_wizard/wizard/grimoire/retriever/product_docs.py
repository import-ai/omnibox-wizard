"""
Product Documentation Retriever

Fetches official OmniBox product documentation from GitHub repository
and returns full content based on user's language preference.
"""

import asyncio
import base64
from functools import partial
from typing import Literal

import httpx
from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.entity.retrieval import Citation, BaseRetrieval
from omnibox_wizard.wizard.grimoire.entity.tools import BaseTool
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever, SearchFunction

GITHUB_API = "https://api.github.com"
OWNER = "import-ai"
REPO = "omnibox-docs"

tracer = trace.get_tracer(__name__)


class ProductDocsRetrieval(BaseRetrieval):
    """Product documentation retrieval result."""
    content: str
    source: Literal["product_docs"] = "product_docs"

    def to_prompt(self, exclude_id: bool = False) -> str:
        return self.content

    def to_citation(self) -> Citation:
        return Citation(
            id=self.id,
            link=f"https://github.com/{OWNER}/{REPO}",
            title="Product Documentation",
            snippet=self.content[:200] + "..." if len(self.content) > 200 else self.content,
            source=self.source,
        )


class ProductDocsRetriever(BaseRetriever):
    """
    Retriever for product documentation from GitHub.

    Fetches docs from import-ai/omnibox-docs repository on initialization
    and returns full content based on user's language preference.
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

    @tracer.start_as_current_span("ProductDocsRetriever.search")
    async def search(
        self,
        query: str = "",
        *,
        lang: str = "简体中文",
        trace_info: TraceInfo | None = None,
    ):
        """Return full product documentation in the requested language."""
        await self._ensure_init()
        lang_key = "zh" if lang == "简体中文" else "en"
        content = self._cache.get(lang_key, "")

        if trace_info:
            trace_info.debug({
                "lang": lang_key,
                "content_length": len(content),
            })

        return [ProductDocsRetrieval(content=content)]

    def get_function(self, tool: BaseTool, **kwargs) -> SearchFunction:
        return partial(self.search, **kwargs)

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "product_docs",
                "display_name": {"zh": "查询产品文档", "en": "Search Product Docs"},
                "description": "Get official OmniBox product documentation (pricing, features, plugins, usage). Use this tool when users ask questions about the product itself.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }
