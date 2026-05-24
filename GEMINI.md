# MCP-Powered GitHub Repo Assistant: Technical Mandates

## Core Architecture
- **Agent Orchestration:** Uses `LangGraph` for stateful, multi-turn reasoning. The graph includes a `Verifier` node to ensure response quality.
- **Protocol:** `Model Context Protocol (MCP)` is used for all tool interactions. Persistent connections are managed via `MCPClientManager` to minimize latency.
- **RAG Pipeline:** 
  - **Ingestion:** Language-aware chunking using `RecursiveCharacterTextSplitter`.
  - **Retrieval:** Hybrid search (Semantic + Keyword) powered by `Qdrant`.

## Development Standards
- **Async First:** All core components (MCP calls, Agent nodes, External APIs) must be asynchronous. Use `httpx` for all HTTP requests.
- **Type Safety:** Maintain strict type hints for all tool definitions and state objects.
- **Testing:** Use `pytest` and `pytest-asyncio` for all tests. Mock LLMs using the `ainvoke` pattern.
- **Tooling:** `Ruff` is used for linting and formatting. Always check compatibility with `pyproject.toml`.

## MCP Tools
All tools must be defined in `src/mcp_server/server.py` using `FastMCP` and then exposed in `src/agent/tools.py` via the `MCPClientManager`.

## API Layer
- **FastAPI:** The project exposes a REST API using FastAPI.
- **Streaming:** Real-time updates are delivered via Server-Sent Events (SSE) at the `/chat/stream` endpoint.
- **CORS:** Enabled by default to support frontend integrations.
