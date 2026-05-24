import json
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _default_server_path() -> str:
    server_path = os.getenv("MCP_SERVER_PATH")
    if server_path:
        return server_path
    return str(Path(__file__).resolve().parents[1] / "mcp_server" / "server.py")


def _stringify_result(result: Any) -> str:
    if result is None:
        return ""

    content = getattr(result, "content", None)
    if content is None:
        return json.dumps(result, ensure_ascii=False, default=str)

    if isinstance(content, list):
        parts = []
        for item in content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "\n".join(parts)

    return str(content)


import asyncio
from contextlib import asynccontextmanager

class MCPClientManager:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.session = None
        self.exit_stack = None

    @classmethod
    async def get_instance(cls):
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @asynccontextmanager
    async def get_session(self):
        if self.session is None:
            async with self._lock:
                if self.session is None:
                    from contextlib import AsyncExitStack
                    self.exit_stack = AsyncExitStack()
                    server_params = StdioServerParameters(
                        command=sys.executable,
                        args=[_default_server_path()],
                    )
                    read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
                    self.session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                    await self.session.initialize()
        yield self.session

async def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    manager = await MCPClientManager.get_instance()
    async with manager.get_session() as session:
        result = await session.call_tool(tool_name, arguments)
        return _stringify_result(result)


@tool("get_repository_info")
async def get_repository_info(repo_name: str):
    """Get detailed information about a GitHub repository."""
    return await _call_mcp_tool("get_repository_info", {"repo_name": repo_name})


@tool("search_repo")
async def search_repo(repo_name: str, query: str):
    """Search for code or files within a GitHub repository."""
    return await _call_mcp_tool("search_repo", {"repo_name": repo_name, "query": query})


@tool("read_file")
async def read_file(repo_name: str, file_path: str):
    """Read the content of a specific file in a GitHub repository."""
    return await _call_mcp_tool("read_file", {"repo_name": repo_name, "file_path": file_path})


@tool("summarize_architecture")
async def summarize_architecture(repo_name: str):
    """Analyze the repository structure to summarize its architecture."""
    return await _call_mcp_tool("summarize_architecture", {"repo_name": repo_name})


@tool("review_pull_request")
async def review_pull_request(repo_name: str, pr_number: int):
    """Review code changes in a specific Pull Request."""
    return await _call_mcp_tool("review_pull_request", {"repo_name": repo_name, "pr_number": pr_number})


@tool("create_github_issue")
async def create_github_issue(repo_name: str, title: str, body: str):
    """Create a new issue in a GitHub repository."""
    return await _call_mcp_tool(
        "create_github_issue",
        {"repo_name": repo_name, "title": title, "body": body},
    )


@tool("trigger_n8n_workflow")
async def trigger_n8n_workflow(webhook_url: str, payload: dict[str, Any]):
    """Trigger an n8n workflow via a webhook URL."""
    return await _call_mcp_tool(
        "trigger_n8n_workflow",
        {"webhook_url": webhook_url, "payload": payload},
    )


repo_assistant_tools = [
    get_repository_info,
    search_repo,
    read_file,
    summarize_architecture,
    review_pull_request,
    create_github_issue,
    trigger_n8n_workflow,
]
