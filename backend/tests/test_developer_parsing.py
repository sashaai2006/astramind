import asyncio
import json

from backend.agents.developer import DeveloperAgent


def test_execute_with_retry_accepts_file_key(monkeypatch):
    async def inner():
        sem = asyncio.Semaphore(1)
        agent = DeveloperAgent(sem)

        class A:
            async def acomplete(self, prompt, json_mode=True, cache_key=None):
                return json.dumps({"file": {"path": "a.txt", "content": "hello"}})

        agent._adapter = A()
        ctx = {"project_id": "testproj", "title": "t", "description": "d"}
        res = await agent._execute_with_retry("prompt", {"name": "step"}, ctx)
        assert isinstance(res, dict)
        assert "files" in res
        assert len(res["files"]) == 1
        assert res["files"][0]["path"] == "a.txt"

    asyncio.run(inner())


def test_execute_with_retry_accepts_top_level_file_dict(monkeypatch):
    async def inner():
        sem = asyncio.Semaphore(1)
        agent = DeveloperAgent(sem)

        class A:
            async def acomplete(self, prompt, json_mode=True, cache_key=None):
                return json.dumps({"path": "b.txt", "content": "bye"})

        agent._adapter = A()
        ctx = {"project_id": "testproj", "title": "t", "description": "d"}
        res = await agent._execute_with_retry("prompt", {"name": "step"}, ctx)
        assert "files" in res
        assert res["files"][0]["path"] == "b.txt"

    asyncio.run(inner())


def test_execute_with_retry_discovers_list_value(monkeypatch):
    async def inner():
        sem = asyncio.Semaphore(1)
        agent = DeveloperAgent(sem)

        class A:
            async def acomplete(self, prompt, json_mode=True, cache_key=None):
                return json.dumps({"response": [{"path": "c.txt", "content": "c"}]})

        agent._adapter = A()
        ctx = {"project_id": "testproj", "title": "t", "description": "d"}
        res = await agent._execute_with_retry("prompt", {"name": "step"}, ctx)
        assert "files" in res
        assert res["files"][0]["path"] == "c.txt"

    asyncio.run(inner())


def test_execute_with_retry_auto_repair(monkeypatch):
    async def inner():
        class A:
            def __init__(self):
                self.calls = 0

            async def acomplete(self, prompt, json_mode=True, cache_key=None):
                self.calls += 1
                # First response is valid JSON but missing files
                if self.calls == 1:
                    return json.dumps({"status": "ok"})
                # On retry (repair prompt), return correct output
                if "IMPORTANT: YOUR PREVIOUS RESPONSE WAS INVALID JSON" in prompt:
                    return json.dumps({"files": [{"path": "fixed.txt", "content": "fixed"}]})
                return json.dumps({"files": []})

        sem = asyncio.Semaphore(1)
        agent = DeveloperAgent(sem)
        agent._adapter = A()
        ctx = {"project_id": "testproj", "title": "t", "description": "d"}
        res = await agent._execute_with_retry("prompt", {"name": "step"}, ctx)
        assert "files" in res
        assert res["files"][0]["path"] == "fixed.txt"

    asyncio.run(inner())