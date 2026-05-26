from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage

from src.agent.assistant import get_app, invoke_agent, get_langfuse_callback
from src.rag.ingest import ingest_repository
from src.rag.retriever import RepoRetriever
from src.agent.task_orchestrator import TaskDecompositionEngine, SubTask
from src.agent.parallel_executor import ParallelExecutor, ExecutionStrategy
from src.api.logging_config import (
    setup_logging,
    get_logger,
    RequestIdMiddleware,
    request_id_ctx,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Logging bootstrap
# ---------------------------------------------------------------------------
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger("mcp.api")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STARTUP_TIME = time.time()
_API_SECRET_KEY = os.getenv("API_SECRET_KEY")
_REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))

# ---------------------------------------------------------------------------
# Swagger / OpenAPI metadata
# ---------------------------------------------------------------------------
tags_metadata = [
    {"name": "Chat", "description": "Conversational RAG chat with LangGraph agent."},
    {"name": "RAG", "description": "Vector search and repository ingestion."},
    {"name": "Orchestrator", "description": "Parallel Agent Task Orchestrator (DAG)."},
    {"name": "System", "description": "Health checks, metrics, and diagnostics."},
]

app = FastAPI(
    title="MCP Repo Assistant API",
    version="2.1.0",
    description=(
        "Production-grade API for repository analysis, MCP tool calling, "
        "RAG hybrid search, and parallel agent task orchestration."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=tags_metadata,
)

# ---------------------------------------------------------------------------
# Middleware – order matters (outermost first)
# ---------------------------------------------------------------------------
# 1. Request-ID tracing
app.add_middleware(RequestIdMiddleware)

# 2. CORS – whitelist from env, defaults to permissive for local dev
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "src" / "api" / "static")),
    name="static",
)

# ---------------------------------------------------------------------------
# Rate Limiting (lightweight, in-memory)
# ---------------------------------------------------------------------------
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
_RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is within rate limit."""
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    hits = _rate_limit_store.get(client_ip, [])
    hits = [t for t in hits if t > window_start]
    if len(hits) >= _RATE_LIMIT_MAX:
        _rate_limit_store[client_ip] = hits
        return False
    hits.append(now)
    _rate_limit_store[client_ip] = hits
    return True


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
async def verify_api_key(request: Request) -> None:
    """If API_SECRET_KEY is set in env, require matching X-API-Key header."""
    if _API_SECRET_KEY is None:
        return  # dev mode – no auth
    key = request.headers.get("X-API-Key")
    if key != _API_SECRET_KEY:
        logger.warning("Rejected request with invalid API key", extra={"path": request.url.path})
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


async def rate_limit_guard(request: Request) -> None:
    """Enforce per-IP rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        logger.warning("Rate limit exceeded", extra={"client_ip": client_ip})
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error: %s", exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "detail": exc.errors(),
            "request_id": request_id_ctx.get("-"),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc),
            "request_id": request_id_ctx.get("-"),
        },
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10000)
    repo_path: str | None = None
    collection_name: str = Field(default="repo_docs", pattern=r"^[a-zA-Z0-9_\-]+$")
    top_k: int = Field(default=5, ge=1, le=20)
    reindex: bool = True


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000)
    repo_path: str | None = None
    collection_name: str = Field(default="repo_docs", pattern=r"^[a-zA-Z0-9_\-]+$")
    top_k: int = Field(default=5, ge=1, le=20)
    reindex: bool = False


class IngestRequest(BaseModel):
    repo_path: str | None = None
    collection_name: str = Field(default="repo_docs", pattern=r"^[a-zA-Z0-9_\-]+$")


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


class ParallelExecutionRequest(BaseModel):
    user_request: str = Field(..., min_length=1, max_length=10000)
    max_concurrent_tasks: int = Field(default=5, ge=1, le=10)
    strategy: ExecutionStrategy = Field(default=ExecutionStrategy.BALANCED)
    timeout_per_task: float = Field(default=30.0, ge=1.0)


# ---------------------------------------------------------------------------
# Prometheus-style metrics (lightweight, no extra dependency)
# ---------------------------------------------------------------------------
_metrics: dict[str, Any] = {
    "requests_total": 0,
    "requests_by_endpoint": {},
    "errors_total": 0,
    "chat_latency_seconds": [],
}


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start

    _metrics["requests_total"] += 1
    path = request.url.path
    _metrics["requests_by_endpoint"][path] = _metrics["requests_by_endpoint"].get(path, 0) + 1
    if response.status_code >= 500:
        _metrics["errors_total"] += 1
    if path in ("/chat", "/chat/stream"):
        _metrics["chat_latency_seconds"].append(round(elapsed, 4))
        # Keep only last 1000 measurements
        if len(_metrics["chat_latency_seconds"]) > 1000:
            _metrics["chat_latency_seconds"] = _metrics["chat_latency_seconds"][-1000:]

    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------
@app.get("/health", tags=["System"], summary="Detailed health check")
def health() -> dict[str, Any]:
    """Comprehensive health check including Qdrant connectivity and uptime."""
    uptime = round(time.time() - _STARTUP_TIME, 2)
    status: dict[str, Any] = {
        "status": "ok",
        "service": "mcp-repo-assistant-api",
        "version": "2.1.0",
        "uptime_seconds": uptime,
    }
    # Check Qdrant connectivity
    try:
        from qdrant_client import QdrantClient

        qdrant_url = os.getenv("QDRANT_URL")
        if qdrant_url:
            client = QdrantClient(url=qdrant_url, timeout=3)
            client.get_collections()
            status["qdrant"] = "connected"
        else:
            status["qdrant"] = "local_storage"
    except Exception as e:
        status["qdrant"] = f"error: {e}"
        status["status"] = "degraded"

    return status


@app.get("/readiness", tags=["System"], summary="Kubernetes readiness probe")
def readiness():
    return {"ready": True}


@app.get("/metrics", tags=["System"], summary="Application metrics")
def metrics():
    """Return lightweight application metrics."""
    latencies = _metrics["chat_latency_seconds"]
    avg_latency = round(sum(latencies) / len(latencies), 4) if latencies else 0
    return {
        "requests_total": _metrics["requests_total"],
        "requests_by_endpoint": _metrics["requests_by_endpoint"],
        "errors_total": _metrics["errors_total"],
        "chat_latency_avg_seconds": avg_latency,
        "chat_latency_p99_seconds": round(sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0, 4),
        "uptime_seconds": round(time.time() - _STARTUP_TIME, 2),
    }


# ---------------------------------------------------------------------------
# RAG endpoints
# ---------------------------------------------------------------------------
@app.post("/ingest", response_model=IngestResponse, tags=["RAG"], dependencies=[Depends(verify_api_key)])
async def ingest(request: IngestRequest) -> IngestResponse:
    repo_path = _resolve_repo_path(request.repo_path)
    logger.info("Starting repository ingestion", extra={"repo_path": repo_path})

    try:
        _, documents = await asyncio.to_thread(
            ingest_repository,
            repo_path,
            request.collection_name,
        )
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    logger.info("Ingestion complete", extra={"docs_indexed": len(documents)})
    return IngestResponse(
        repo_path=repo_path,
        collection_name=request.collection_name,
        documents_indexed=len(documents),
    )


@app.post("/search", response_model=SearchResponse, tags=["RAG"], dependencies=[Depends(verify_api_key)])
async def search(request: SearchRequest) -> SearchResponse:
    repo_path = _resolve_repo_path(request.repo_path)

    try:
        retriever = _build_retriever(request.collection_name)
        if request.reindex:
            await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
        documents = await asyncio.to_thread(retriever.search, request.query, request.top_k)
    except Exception as exc:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc

    return SearchResponse(
        query=request.query,
        hits=_to_search_hits(documents),
        collection_name=request.collection_name,
        repo_path=repo_path,
    )


# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["Chat"],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_guard)],
)
async def chat(request: ChatRequest) -> ChatResponse:
    repo_path = _resolve_repo_path(request.repo_path)
    logger.info("Chat request received", extra={"question_len": len(request.question)})

    try:
        async with asyncio.timeout(_REQUEST_TIMEOUT):
            retriever = _build_retriever(request.collection_name)
            if request.reindex:
                await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
            documents = await asyncio.to_thread(retriever.search, request.question, request.top_k)
            hits = _to_search_hits(documents)
            answer_raw = await invoke_agent(_build_context_prompt(request.question, hits))
            answer = str(answer_raw) if not isinstance(answer_raw, str) else answer_raw
    except asyncio.TimeoutError:
        logger.error("Chat request timed out after %ds", _REQUEST_TIMEOUT)
        raise HTTPException(status_code=504, detail=f"Request timed out after {_REQUEST_TIMEOUT}s.")
    except Exception as exc:
        logger.exception("Chat failed")
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
        logger.exception("Streaming error")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@app.post(
    "/chat/stream",
    tags=["Chat"],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_guard)],
)
async def chat_stream(request: ChatRequest):
    repo_path = _resolve_repo_path(request.repo_path)
    logger.info("Chat stream request", extra={"question_len": len(request.question)})

    try:
        retriever = _build_retriever(request.collection_name)
        if request.reindex:
            await asyncio.to_thread(ingest_repository, repo_path, request.collection_name)
        documents = await asyncio.to_thread(retriever.search, request.question, request.top_k)
        hits = _to_search_hits(documents)

        full_prompt = _build_context_prompt(request.question, hits)

        return StreamingResponse(
            _stream_agent_updates(full_prompt),
            media_type="text/event-stream",
        )
    except Exception as exc:
        logger.exception("Streaming failed")
        raise HTTPException(status_code=500, detail=f"Streaming failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Static HTML root
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, tags=["System"])
def root():
    index_file = PROJECT_ROOT / "src" / "api" / "static" / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return HTMLResponse("<h1>MCP Repo Assistant API</h1><p>Static index.html not found</p>")


# ---------------------------------------------------------------------------
# Parallel Orchestrator endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/api/tasks/execute-parallel",
    tags=["Orchestrator"],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_guard)],
)
async def execute_parallel(request: ParallelExecutionRequest):
    """Decompose a complex request into subtasks and execute them in parallel."""
    try:
        orchestrator = TaskDecompositionEngine()

        logger.info("Decomposing request", extra={"request_len": len(request.user_request)})
        execution_plan = await orchestrator.decompose_request(
            user_request=request.user_request,
            time_limit=int(request.timeout_per_task * 4),
        )

        async def execute_single_task_via_agent(
            task_id: str, subtask_def: SubTask, dependencies_outputs: str
        ) -> str:
            from src.agent.prompts import get_prompt

            subtask_prompt = get_prompt(
                "SUBTASK_EXECUTION_PROMPT",
                task_name=subtask_def.name,
                task_description=subtask_def.description,
                user_request=request.user_request,
                dependencies_outputs=dependencies_outputs,
            )
            return await invoke_agent(subtask_prompt)

        executor = ParallelExecutor(
            max_concurrent_tasks=request.max_concurrent_tasks,
            execution_strategy=request.strategy,
            timeout_per_task=request.timeout_per_task,
        )

        results = await executor.execute_workflow(
            execution_plan=execution_plan,
            execution_func=execute_single_task_via_agent,
            context={"user_request": request.user_request},
        )

        return {
            "success": True,
            "execution_plan": {
                "analysis": execution_plan.analysis,
                "subtasks": [st.model_dump() for st in execution_plan.subtasks],
                "execution_waves": execution_plan.execution_waves,
            },
            "final_answer": results["final_answer"],
            "task_outputs": results["task_outputs"],
            "task_statuses": results["task_statuses"],
            "task_errors": results["task_errors"],
            "wave_results": results["wave_results"],
            "metrics": results["metrics"],
        }
    except Exception as exc:
        logger.exception("Parallel Execution failed")
        raise HTTPException(status_code=500, detail=f"Parallel Execution failed: {exc}")


@app.post(
    "/api/tasks/execute-parallel/stream",
    tags=["Orchestrator"],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_guard)],
)
async def execute_parallel_stream(request: ParallelExecutionRequest):
    """Stream parallel execution progress via Server-Sent Events (SSE)."""

    async def _stream_execution():
        try:
            orchestrator = TaskDecompositionEngine()

            yield f"data: {json.dumps({'event': 'decomposing', 'data': {}})}\n\n"

            execution_plan = await orchestrator.decompose_request(
                user_request=request.user_request,
                time_limit=int(request.timeout_per_task * 4),
            )

            plan_data = {
                "analysis": execution_plan.analysis,
                "subtasks": [st.model_dump() for st in execution_plan.subtasks],
                "execution_waves": execution_plan.execution_waves,
            }
            yield f"data: {json.dumps({'event': 'decomposed', 'data': plan_data})}\n\n"

            async def execute_single_task_via_agent(
                task_id: str, subtask_def: SubTask, dependencies_outputs: str
            ) -> str:
                from src.agent.prompts import get_prompt

                subtask_prompt = get_prompt(
                    "SUBTASK_EXECUTION_PROMPT",
                    task_name=subtask_def.name,
                    task_description=subtask_def.description,
                    user_request=request.user_request,
                    dependencies_outputs=dependencies_outputs,
                )
                return await invoke_agent(subtask_prompt)

            executor = ParallelExecutor(
                max_concurrent_tasks=request.max_concurrent_tasks,
                execution_strategy=request.strategy,
                timeout_per_task=request.timeout_per_task,
            )

            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def status_callback(msg_dict: dict[str, Any]) -> None:
                await queue.put(msg_dict)

            async def run_workflow():
                try:
                    results = await executor.execute_workflow(
                        execution_plan=execution_plan,
                        execution_func=execute_single_task_via_agent,
                        status_callback=status_callback,
                        context={"user_request": request.user_request},
                    )
                    await queue.put({"event": "complete", "data": results})
                except Exception as e:
                    await queue.put({"event": "error", "data": str(e)})

            workflow_task = asyncio.create_task(run_workflow())

            while not workflow_task.done() or not queue.empty():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield f"data: {json.dumps(msg)}\n\n"
                    queue.task_done()
                except asyncio.TimeoutError:
                    continue

            if workflow_task.exception():
                raise workflow_task.exception()  # type: ignore[misc]

        except Exception as exc:
            logger.exception("Parallel stream failed")
            yield f"data: {json.dumps({'event': 'error', 'data': str(exc)})}\n\n"

    return StreamingResponse(_stream_execution(), media_type="text/event-stream")
