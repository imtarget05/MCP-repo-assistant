from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from src.agent.assistant import get_app, invoke_agent, get_langfuse_callback
from src.rag.ingest import ingest_repository
from src.rag.retriever import RepoRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    repo_path: str | None = None
    collection_name: str = "repo_docs"
    top_k: int = Field(default=5, ge=1, le=20)
    reindex: bool = True


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    repo_path: str | None = None
    collection_name: str = "repo_docs"
    top_k: int = Field(default=5, ge=1, le=20)
    reindex: bool = False


class IngestRequest(BaseModel):
    repo_path: str | None = None
    collection_name: str = "repo_docs"


class SearchHit(BaseModel):
    source: str | None = None
    content: str
    absolute_path: str | None = None


class ChatResponse(BaseModel):
    answer: str
    contexts: list[SearchHit]
    collection_name: str
    repo_path: str


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    collection_name: str
    repo_path: str


class IngestResponse(BaseModel):
    repo_path: str
    collection_name: str
    documents_indexed: int


app = FastAPI(
    title="MCP Repo Assistant API",
    version="2.0.0",
    description="Production-style API for repository analysis, MCP tool calling, and RAG.",
)

app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "src" / "api" / "static")),
    name="static",
)


def _resolve_repo_path(repo_path: str | None) -> str:
    return repo_path or str(PROJECT_ROOT)


def _to_search_hits(documents: list[Any]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for document in documents:
        metadata = getattr(document, "metadata", {}) or {}
        hits.append(
            SearchHit(
                source=metadata.get("source"),
                absolute_path=metadata.get("absolute_path"),
                content=getattr(document, "page_content", str(document)),
            )
        )
    return hits


def _build_context_prompt(question: str, hits: list[SearchHit]) -> str:
    context_block = "\n\n".join(
        f"[Context {index + 1}]\n{hit.content}" for index, hit in enumerate(hits)
    )
    return (
        "Answer using only the repository context below. "
        "If the context is insufficient, say so clearly.\n\n"
        f"{context_block}\n\nQuestion: {question}"
    )


def _build_retriever(collection_name: str) -> RepoRetriever:
    return RepoRetriever(collection_name=collection_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "mcp-repo-assistant-api",
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    repo_path = _resolve_repo_path(request.repo_path)

    try:
        _, documents = await asyncio.to_thread(
            ingest_repository,
            repo_path,
            request.collection_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return IngestResponse(
        repo_path=repo_path,
        collection_name=request.collection_name,
        documents_indexed=len(documents),
    )


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    repo_path = _resolve_repo_path(request.repo_path)

    try:
        retriever = _build_retriever(request.collection_name)
        if request.reindex:
            await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
        documents = await asyncio.to_thread(retriever.search, request.query, request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc

    return SearchResponse(
        query=request.query,
        hits=_to_search_hits(documents),
        collection_name=request.collection_name,
        repo_path=repo_path,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    repo_path = _resolve_repo_path(request.repo_path)

    try:
        retriever = _build_retriever(request.collection_name)
        if request.reindex:
            await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
        documents = await asyncio.to_thread(retriever.search, request.question, request.top_k)
        hits = _to_search_hits(documents)
        answer_raw = await invoke_agent(_build_context_prompt(request.question, hits))
        answer = str(answer_raw) if not isinstance(answer_raw, str) else answer_raw
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc

    return ChatResponse(
        answer=answer,
        contexts=hits,
        collection_name=request.collection_name,
        repo_path=repo_path,
    )


async def _stream_agent_updates(message: str):
    """Stream updates from the LangGraph agent in SSE format."""
    agent = get_app()
    from src.agent.assistant import AgentState
    inputs: AgentState = {"messages": [HumanMessage(content=message)], "is_valid": False, "retry_count": 0, "reasoning": ""}
    callbacks = get_langfuse_callback()
    from typing import Any
    config: Any = {"callbacks": callbacks} if callbacks else None

    try:
        async for output in agent.astream(inputs, stream_mode="updates", config=config):
            for node, data in output.items():
                chunk = {"node": node, "data": {}}

                if node == "agent":
                    msg = data["messages"][-1]
                    if msg.tool_calls:
                        chunk["data"]["tool_calls"] = [
                            {"name": tc["name"], "args": tc["args"]} for tc in msg.tool_calls
                        ]
                    elif msg.content:
                        chunk["data"]["content"] = msg.content
                elif node == "verifier":
                    chunk["data"]["is_valid"] = data.get("is_valid", False)
                elif node == "tools":
                    chunk["data"]["status"] = "Tool execution completed"

                yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    repo_path = _resolve_repo_path(request.repo_path)

    try:
        retriever = _build_retriever(request.collection_name)
        if request.reindex:
            await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
        documents = await asyncio.to_thread(retriever.search, request.question, request.top_k)
        hits = _to_search_hits(documents)

        full_prompt = _build_context_prompt(request.question, hits)

        return StreamingResponse(
            _stream_agent_updates(full_prompt),
            media_type="text/event-stream"
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Streaming failed: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
def root():
    index_file = PROJECT_ROOT / "src" / "api" / "static" / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return HTMLResponse("<h1>MCP Repo Assistant API</h1><p>Static index.html not found</p>")
