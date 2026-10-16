"""Generated OpenAPI document."""

from fastapi.testclient import TestClient


def test_openapi_lists_m2_routes_and_not_ai(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "AI Novel Writer"
    assert document["info"]["version"] == "0.3.0"
    assert "/api/v1/health" in document["paths"]
    assert "get" in document["paths"]["/api/v1/health"]
    assert "/api/v1/novels" in document["paths"]
    assert "/api/v1/chapters/{chapter_id}" in document["paths"]
    assert "put" in document["paths"]["/api/v1/chapters/{chapter_id}"]
    assert "get" in document["paths"]["/api/v1/chapters/{chapter_id}/versions"]
    assert "post" in document["paths"]["/api/v1/chapters/{chapter_id}/restore"]
    assert "post" in document["paths"]["/api/v1/novels/{novel_id}/export"]
    assert "/api/v1/ai/tasks" not in document["paths"]


def test_docs_page_is_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
