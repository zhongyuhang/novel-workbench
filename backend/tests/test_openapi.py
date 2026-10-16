"""Generated OpenAPI document."""

from fastapi.testclient import TestClient


def test_openapi_lists_m3_routes(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "AI Novel Writer"
    assert document["info"]["version"] == "0.4.0"
    assert "/api/v1/health" in document["paths"]
    assert "get" in document["paths"]["/api/v1/health"]
    assert "/api/v1/novels" in document["paths"]
    assert "/api/v1/chapters/{chapter_id}" in document["paths"]
    assert "put" in document["paths"]["/api/v1/chapters/{chapter_id}"]
    assert "get" in document["paths"]["/api/v1/chapters/{chapter_id}/versions"]
    assert "post" in document["paths"]["/api/v1/chapters/{chapter_id}/restore"]
    assert "post" in document["paths"]["/api/v1/novels/{novel_id}/export"]
    assert "post" in document["paths"]["/api/v1/ai/tasks"]
    assert "get" in document["paths"]["/api/v1/ai/tasks/{task_id}/events"]
    assert "post" in document["paths"]["/api/v1/ai/tasks/{task_id}/cancel"]
    assert "post" in document["paths"]["/api/v1/ai/tasks/{task_id}/accept"]
    assert "post" in document["paths"]["/api/v1/ai/tasks/{task_id}/reject"]
    assert "get" in document["paths"]["/api/v1/settings/models"]
    assert "post" in document["paths"]["/api/v1/settings/models/test"]


def test_docs_page_is_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
