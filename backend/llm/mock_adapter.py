from __future__ import annotations

import json
from typing import Optional

from .adapter import BaseLLMAdapter

class MockLLMAdapter(BaseLLMAdapter):

    async def acomplete(self, prompt: str, json_mode: bool = False, cache_key: Optional[str] = None) -> str:
        marker = "FILES_SPEC::"
        if marker in prompt:
            _, payload = prompt.split(marker, maxsplit=1)
            payload = payload.strip()
            try:
                files = json.loads(payload)
            except json.JSONDecodeError:
                files = [
                    {
                        "path": "README.md",
                        "content": "# Mock output\nThis is a fallback artifact.",
                    }
                ]
            return json.dumps({"files": files})

        return json.dumps(
            {
                "files": [
                    {
                        "path": "notes.md",
                        "content": "Mock adapter fallback file.",
                    }
                ]
            }
        )
