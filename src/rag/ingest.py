import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.documents import Document

load_dotenv()

from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

TEXT_FILE_NAMES = {"Dockerfile", "Makefile", "README", "README.md"}
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".ini",
    ".cfg",
    ".sh",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    "data/qdrant",
}


def _is_excluded(path: Path) -> bool:
    path_string = str(path)
    return any(part in path.parts or part in path_string for part in EXCLUDED_PARTS)


def _is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_EXTENSIONS or path.name in TEXT_FILE_NAMES


def load_repository_documents(repo_path: str | Path) -> list[Document]:
    root = Path(repo_path).resolve()
    documents: list[Document] = []
    
    # Initialize splitters for different languages
    python_splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.PYTHON, chunk_size=2000, chunk_overlap=200
    )
    md_splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN, chunk_size=2000, chunk_overlap=200
    )
    default_splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000, chunk_overlap=200
    )

    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path) or not _is_text_file(path):
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if not content.strip():
            continue

        metadata = {
            "source": str(path.relative_to(root)),
            "absolute_path": str(path),
            "repo_root": str(root),
        }
        
        # Split documents based on file type
        if path.suffix == ".py":
            docs = python_splitter.create_documents([content], [metadata])
        elif path.suffix == ".md":
            docs = md_splitter.create_documents([content], [metadata])
        else:
            docs = default_splitter.create_documents([content], [metadata])
            
        documents.extend(docs)

    return documents


def ingest_repository(repo_path: str | Path | None = None, collection_name: str = "repo_docs"):
    from src.rag.retriever import RepoRetriever

    root = Path(repo_path) if repo_path is not None else Path(__file__).resolve().parents[2]
    retriever = RepoRetriever(collection_name=collection_name)
    docs = load_repository_documents(root)

    print(f"Indexing {len(docs)} documents from {root}...")
    retriever.index_repo(docs)
    print("Ingestion complete.")
    return retriever, docs

if __name__ == "__main__":
    ingest_repository()
