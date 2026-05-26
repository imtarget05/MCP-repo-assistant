import os
import time
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api.app import app


def test_cors_headers():
    client = TestClient(app)
    # Test CORS options preflight
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8000"


def test_api_key_authentication():
    # Patch API_SECRET_KEY to verify authentication
    with patch("src.api.app._API_SECRET_KEY", "super-secret-key-123"):
        client = TestClient(app)
        
        # 1. Reject without key
        response = client.post("/ingest", json={"repo_path": None})
        assert response.status_code == 403
        assert "Invalid or missing API key" in response.json()["detail"]

        # 2. Reject with wrong key
        response = client.post(
            "/ingest",
            json={"repo_path": None},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 403

        # 3. Accept with correct key
        # Mock ingest_repository so we don't do real index in tests
        with patch("src.api.app.ingest_repository") as mock_ingest:
            mock_ingest.return_value = (None, [])
            response = client.post(
                "/ingest",
                json={"repo_path": None},
                headers={"X-API-Key": "super-secret-key-123"},
            )
            assert response.status_code == 200


def test_rate_limiting():
    # Make sure we trigger rate limiting using a lower threshold or custom IP
    client = TestClient(app)
    
    # Custom limit to 5 just for test to be fast
    with patch("src.api.app._RATE_LIMIT_MAX", 5):
        # We need to clear store first to be clean
        with patch("src.api.app._rate_limit_store", {}):
            # Mock invoke_agent, RepoRetriever and ingest_repository to run instantly
            from unittest.mock import AsyncMock
            with patch("src.api.app.invoke_agent", new_callable=AsyncMock) as mock_invoke, \
                 patch("src.api.app.ingest_repository") as mock_ingest, \
                 patch("src.api.app.RepoRetriever") as mock_retriever:
                
                mock_invoke.return_value = "Test response"
                mock_ingest.return_value = (None, [])
                
                # Send 5 requests -> OK
                for _ in range(5):
                    response = client.post("/chat", json={"question": "Test", "reindex": False})
                    assert response.status_code != 429

                # 6th request -> Rate limited (429)
                response = client.post("/chat", json={"question": "Test", "reindex": False})
                assert response.status_code == 429
                assert "Too many requests" in response.json()["detail"]

