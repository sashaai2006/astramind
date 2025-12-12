from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from backend.memory.vector_store import get_project_memory, get_semantic_cache
from backend.settings import get_settings
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "duckduckgo"

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source}


class ResearcherAgent:
    """
    Web search agent used by the DAG.

    - Primary provider: DuckDuckGo (no key)
    - Optional fallback: Google Custom Search (requires API key + CSE id)
    - Caches results in SemanticCache and also stores in ProjectMemory
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache = get_semantic_cache()

    def _cache_key(self, query: str, provider: str) -> str:
        return f"web_search::{provider}::{query.strip()}"

    async def search(self, query: str, project_id: Optional[str] = None, max_results: int = 5) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"query": "", "provider": None, "results": [], "cached": False}

        provider = self._settings.search_provider
        max_results = max(1, min(int(max_results), int(self._settings.max_search_results)))

        # Semantic cache lookup
        cache_key = self._cache_key(query, provider)
        cached = self._cache.get(cache_key, filter_metadata={"type": "web_search", "provider": provider})
        if cached:
            try:
                payload = json.loads(cached)
                payload["cached"] = True
                return payload
            except Exception:
                LOGGER.debug("Failed to parse cached web search payload; ignoring cache.")

        # Run provider
        payload: Dict[str, Any]
        try:
            if provider == "google":
                payload = await self._search_google(query, max_results=max_results)
            else:
                payload = await self._search_duckduckgo(query, max_results=max_results)
        except Exception as e:
            LOGGER.warning("Web search failed via %s: %s", provider, e)
            # Fallback: try Google if configured
            if provider != "google" and self._settings.google_search_api_key and self._settings.google_search_engine_id:
                payload = await self._search_google(query, max_results=max_results)
                provider = "google"
            else:
                payload = {"query": query, "provider": provider, "results": [], "error": str(e)[:300]}

        payload.setdefault("query", query)
        payload.setdefault("provider", provider)
        payload["cached"] = False
        payload["timestamp_ms"] = int(time.time() * 1000)

        # Store in semantic cache
        try:
            self._cache.set(
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                metadata={"type": "web_search", "provider": provider},
            )
        except Exception:
            LOGGER.debug("Failed to write web search results to semantic cache.", exc_info=True)

        # Store in project memory too (so LLM can retrieve later even if state isn't threaded)
        if project_id:
            try:
                pm = get_project_memory(project_id)
                pm.add_context(
                    content=f"WEB RESEARCH\nQuery: {query}\nProvider: {provider}\n\n{self._format_for_memory(payload)}",
                    context_type="research",
                    metadata={"query": query, "provider": provider},
                )
            except Exception:
                LOGGER.debug("Failed to store research in project memory.", exc_info=True)

        return payload

    async def search_for_tech(self, tech_name: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        q = f"{tech_name} latest best practices 2025 official documentation"
        return await self.search(q, project_id=project_id, max_results=5)

    async def search_for_examples(self, tech: str, task: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        q = f"{tech} {task} example code best practices"
        return await self.search(q, project_id=project_id, max_results=5)

    def _format_for_memory(self, payload: Dict[str, Any]) -> str:
        results = payload.get("results", []) or []
        lines: List[str] = []
        for r in results[:10]:
            try:
                title = str(r.get("title", "")).strip()
                url = str(r.get("url", "")).strip()
                snippet = str(r.get("snippet", "")).strip()
                if title or url:
                    lines.append(f"- {title} ({url})")
                if snippet:
                    lines.append(f"  {snippet}")
            except Exception:
                continue
        return "\n".join(lines)

    async def _search_duckduckgo(self, query: str, max_results: int) -> Dict[str, Any]:
        # Prefer duckduckgo-search package if available; fallback to HTML endpoint otherwise.
        try:
            from duckduckgo_search import DDGS  # type: ignore
            from duckduckgo_search.exceptions import RatelimitException  # type: ignore

            # DDGS is synchronous, run in thread pool
            def _sync_search():
                results: List[SearchResult] = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append(
                            SearchResult(
                                title=str(r.get("title", "")),
                                url=str(r.get("href", "")),
                                snippet=str(r.get("body", "")),
                                source="duckduckgo",
                            )
                        )
                return results

            results = await asyncio.to_thread(_sync_search)
            if results:
                return {"query": query, "provider": "duckduckgo", "results": [r.to_dict() for r in results]}
            # If empty, fall through to HTML fallback
        except RatelimitException:
            LOGGER.warning("DuckDuckGo rate limit hit, trying HTML fallback")
        except Exception as e:
            LOGGER.debug("DuckDuckGo library search failed: %s, trying HTML fallback", e)
            # HTML fallback (best effort)
            url = "https://duckduckgo.com/html/"
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(url, data={"q": query})
                resp.raise_for_status()
                text = resp.text
            # Minimal parsing without external deps (regex-based, best effort)
            results: List[SearchResult] = []

            # DuckDuckGo HTML uses result blocks; try to extract anchors + optional snippets
            anchor_re = re.compile(r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.IGNORECASE | re.DOTALL)
            snippet_re = re.compile(r'class="result__snippet"[^>]*>(?P<snippet>.*?)</', re.IGNORECASE | re.DOTALL)

            anchors = list(anchor_re.finditer(text))
            for m in anchors[: max_results * 2]:  # scan a bit more to find matching snippets
                if len(results) >= max_results:
                    break
                href = (m.group("href") or "").strip()
                title_raw = (m.group("title") or "").strip()
                title = re.sub(r"<[^>]+>", "", title_raw).strip()

                # Find snippet near anchor
                snippet = ""
                window = text[m.end() : m.end() + 800]
                sm = snippet_re.search(window)
                if sm:
                    snippet_raw = (sm.group("snippet") or "").strip()
                    snippet = re.sub(r"<[^>]+>", "", snippet_raw).strip()

                if title and href:
                    results.append(SearchResult(title=title, url=href, snippet=snippet, source="duckduckgo"))
            return {"query": query, "provider": "duckduckgo", "results": [r.to_dict() for r in results]}

    async def _search_google(self, query: str, max_results: int) -> Dict[str, Any]:
        api_key = self._settings.google_search_api_key
        cx = self._settings.google_search_engine_id
        if not api_key or not cx:
            raise RuntimeError("Google search is not configured (missing google_search_api_key / google_search_engine_id)")

        # Google Custom Search returns up to 10 items per request
        num = max(1, min(max_results, 10))
        params = {"key": api_key, "cx": cx, "q": query, "num": num}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
            resp.raise_for_status()
            data = resp.json()
        items = data.get("items", []) or []
        results: List[SearchResult] = []
        for it in items[:num]:
            results.append(
                SearchResult(
                    title=str(it.get("title", "")),
                    url=str(it.get("link", "")),
                    snippet=str(it.get("snippet", "")),
                    source="google",
                )
            )
        return {"query": query, "provider": "google", "results": [r.to_dict() for r in results]}

