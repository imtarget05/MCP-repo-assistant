import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse, RetrievalMode
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from langchain_core.documents import Document

load_dotenv()


def _default_storage_path() -> Path:
    configured_path = os.getenv("QDRANT_PATH")
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parents[2] / "data" / "qdrant"


class RepoRetriever:
    def __init__(self, collection_name: str = "repo_docs", storage_path: str | Path | None = None):
        self.collection_name = collection_name
        self.embeddings = OpenAIEmbeddings()
        self.sparse_embeddings = FastEmbedSparse(model_name="Qdrant/bm25")
        
        qdrant_url = os.getenv("QDRANT_URL")
        if qdrant_url:
            # Connect to remote Qdrant server (e.g., in Docker Compose)
            self.client = QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY"))
        else:
            # Local file-based storage
            self.storage_path = Path(storage_path) if storage_path is not None else _default_storage_path()
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.storage_path))
        
        # Upgrade check: If collection exists but has no sparse vectors, delete it
        # so QdrantVectorStore can recreate it with BOTH dense and sparse vectors enabled.
        if self.client.collection_exists(collection_name=self.collection_name):
            collection_info = self.client.get_collection(collection_name=self.collection_name)
            # If sparse vectors config is missing or empty, migrate the collection
            if not collection_info.config.sparse_vectors_config:
                self.client.delete_collection(collection_name=self.collection_name)
        
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=self.embeddings,
            sparse_embedding=self.sparse_embeddings,
            retrieval_mode=RetrievalMode.Hybrid,
        )

    def index_repo(self, documents: list[Document]):
        """Index repository documents."""
        self.vector_store.add_documents(documents)

    def search(self, query: str, k: int = 5):
        """Search for relevant code/docs using hybrid search (Semantic + Keyword)."""
        return self.vector_store.similarity_search(query, k=k)
