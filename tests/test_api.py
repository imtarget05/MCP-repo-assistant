import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from src.api.app import app


class FakeRetriever:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def search(self, query: str, k: int = 5):
        return [
            Document(
                page_content=f"Matched context for: {query}",
                metadata={"source": "README.md", "absolute_path": "/repo/README.md"},
            )
        ]


class TestApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    @patch("src.api.app.invoke_agent", new_callable=AsyncMock)
    @patch("src.api.app.ingest_repository")
    @patch("src.api.app.RepoRetriever", side_effect=FakeRetriever)
    def test_chat_endpoint(self, mock_retriever, mock_ingest, mock_invoke_agent):
        mock_ingest.return_value = (None, [Document(page_content="x", metadata={})])
        mock_invoke_agent.return_value = "This is a practical answer."

        response = self.client.post(
            "/chat",
            json={
                "question": "What does this project do?",
                "repo_path": "/Users/mainguyenbinhtan/Downloads/mcp-repo-assistant",
                "collection_name": "test_collection",
                "top_k": 3,
                "reindex": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer"], "This is a practical answer.")
        self.assertTrue(body["contexts"])
        self.assertEqual(body["collection_name"], "test_collection")
