import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage
from langchain_core.documents import Document

from src.api.app import app


class FakeLLM:
    def __init__(self, response_text: str = "This is a valid mock response with high quality content."):
        self.response_text = response_text
        self.ainvoke = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = response_text
        self.ainvoke.return_value = mock_response

    def bind_tools(self, tools):
        self.tools = tools
        return self


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def test_client():
    return TestClient(app)
