"""
Product Documentation Handler

Fetches official OmniBox product documentation from GitHub repository
and returns full content based on user's language preference.
"""

import asyncio
import base64
import re

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
        self._cache: dict[str, list[dict]] = {"zh": [], "en": []}
        self._initialized = False

    async def _fetch_all(self, path: str) -> list[dict]:
        """Recursively fetch all .md files from a directory and return as list."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        files = []

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
                        # Use relative path from docs/lang/ directory
                        relative_path = item['path'].replace(f"docs/{path.split('/')[-1]}/", "")
                        files.append({"path": relative_path, "content": content})
                    elif item.get("type") == "dir":
                        await fetch(client, item["path"])
            except Exception as e:
                tracer.get_current_span().record_exception(e)

        async with httpx.AsyncClient(base_url=GITHUB_API, timeout=30.0) as client:
            await fetch(client, path)
        return files

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

    def _remove_images(self, content: str) -> str:
        """Remove markdown image syntax from content.

        Removes:
        - ![alt](url)
        - ![alt](url "title")
        - ![alt](url){width=...} and other attribute blocks
        """
        # Pattern to match markdown images with optional attribute block
        # Matches: ![alt](url) or ![alt](url "title") or ![alt](url){width=100}
        image_pattern = r'!\[([^\]]*)\]\([^)]+\)(?:\{[^}]*\})?'
        return re.sub(image_pattern, '', content)

    def _convert_markdown_links(self, content: str, lang_key: str) -> str:
        """Convert internal markdown links to absolute URLs.

        Rules:
        - [text](file.md) -> [text](https://www.omnibox.pro/docs/zh-cn/file)  (zh)
        - [text](file.md#anchor) -> [text](https://www.omnibox.pro/docs/file#anchor)  (en)
        - [text](./file.md) -> [text](https://www.omnibox.pro/docs/zh-cn/file)
        - # path/file.md -> [path/file](https://www.omnibox.pro/docs/zh-cn/path/file)
        - External links (http/https) are preserved
        - Images (![) are removed, not converted
        """
        base_url = "https://www.omnibox.pro/docs"
        lang_path = "/zh-cn" if lang_key == "zh" else ""

        def replace_link(match):
            full_text = match.group(0)
            alt_text = match.group(1)
            link_path = match.group(2)

            # Skip external links
            if link_path.startswith(('http://', 'https://', 'mailto:')):
                return full_text

            # Skip same-page anchor links
            if link_path.startswith('#'):
                return full_text

            # Extract anchor if present
            anchor = ''
            if '#' in link_path:
                link_path, anchor = link_path.split('#', 1)

            # Clean up the path
            if link_path.endswith('.md'):
                link_path = link_path[:-3]

            # Remove leading ./ or ../
            link_path = link_path.lstrip('./')

            # Handle index files
            if link_path.endswith('index'):
                link_path = link_path[:-5] or ''

            # Build absolute URL
            url_path = f"{base_url}{lang_path}"
            if link_path:
                url_path += f"/{link_path}"
            if anchor:
                url_path += f"#{anchor}"

            return f"[{alt_text}]({url_path})"

        # Regex pattern for markdown links (not images)
        # Negative lookbehind to skip images: !\[
        pattern = r'(?<!!)\[([^\]]+)\]\(([^)]+)\)'
        content = re.sub(pattern, replace_link, content)

        # Pattern 2: Handle double-bracket references [[file.md#section]]
        # These are internal document references that LLM sometimes copies
        def replace_bracket_ref(match):
            ref = match.group(1)

            # Skip external URLs
            if ref.startswith(('http://', 'https://', 'mailto:')):
                return match.group(0)

            # Extract anchor if present
            anchor = ''
            if '#' in ref:
                ref, anchor = ref.split('#', 1)

            # Clean up the path
            if ref.endswith('.md'):
                ref = ref[:-3]
            ref = ref.lstrip('./')

            # Build display text (use anchor name or last path segment)
            if anchor:
                display_text = anchor.replace('-', ' ')
            elif ref:
                display_text = ref.split('/')[-1] or 'documentation'
            else:
                display_text = 'documentation'

            # Build absolute URL
            url_path = f"{base_url}{lang_path}"
            if ref:
                url_path += f"/{ref}"
            if anchor:
                url_path += f"#{anchor}"

            return f"[{display_text}]({url_path})"

        # Match [[...]] but not already converted markdown links
        bracket_pattern = r'\[\[([^\]]+)\]\]'
        content = re.sub(bracket_pattern, replace_bracket_ref, content)

        # Pattern 3: Convert heading-style file references (# path/file.md) to clickable links
        # These are generated by _fetch_all when combining documents
        def replace_heading_file_ref(match):
            file_path = match.group(1)

            # Clean up the path
            if file_path.endswith('.md'):
                file_path = file_path[:-3]

            # Build absolute URL
            url_path = f"{base_url}{lang_path}"
            if file_path:
                url_path += f"/{file_path}"

            return f"# link:{url_path}"

        # Match lines that start with # followed by a .md file path
        # Examples: "# applications/qq-assistant.md" or "# browser-extension.md"
        heading_pattern = r'^#\s+([\w./-]+\.md)\s*$'
        content = re.sub(heading_pattern, replace_heading_file_ref, content, flags=re.MULTILINE)

        return content

    def _extract_name_from_content(self, content: str) -> str:
        """Extract name from first line of content (typically markdown title)."""
        first_line = content.strip().split('\n')[0] if content else ""
        # Remove leading # and whitespace
        return first_line.lstrip('#').strip() or ""

    def _build_resource_url(self, file_path: str, lang_key: str) -> str:
        """Build resource URL from file path and language."""
        base_url = "https://www.omnibox.pro/docs"
        lang_path = "/zh-cn" if lang_key == "zh" else ""

        # Remove .md extension
        if file_path.endswith('.md'):
            file_path = file_path[:-3]

        return f"{base_url}{lang_path}/{file_path}"

    def get_function(self, tool: BaseTool, **kwargs) -> ResourceFunction:
        """Return a function that fetches product docs and returns ResourceToolResult."""
        lang = kwargs.get("lang", "简体中文")

        async def _product_docs() -> ResourceToolResult:
            await self._ensure_init()
            lang_key = "zh" if lang == "简体中文" else "en"
            files = self._cache.get(lang_key, [])

            if not files:
                return ResourceToolResult(
                    success=False,
                    error="Failed to fetch product documentation."
                )

            resources = []
            for file_info in files:
                file_path = file_info["path"]
                content = file_info["content"]

                # Process content
                content = self._remove_images(content)
                content = self._convert_markdown_links(content, lang_key)

                # Build ResourceInfo
                name = self._extract_name_from_content(content)
                resource_id = self._build_resource_url(file_path, lang_key)

                resources.append(ResourceInfo(
                    id=resource_id,
                    name=name,
                    resource_type="link",
                    content=content,
                    updated_at=None,
                ))

            return ResourceToolResult(
                success=True,
                data=resources,
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
                    "This tool requires NO parameters - call it with empty arguments: {}. "
                    "Documentation links are provided as absolute URLs (e.g., https://www.omnibox.pro/docs/zh-cn/page-name)."
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
