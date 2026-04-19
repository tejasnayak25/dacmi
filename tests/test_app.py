import threading

from fastapi.testclient import TestClient

import app as app_module


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "MEMORY_FILE", tmp_path / "memories.json")
    monkeypatch.setattr(app_module, "MEMORY_LOCK", threading.Lock())
    return TestClient(app_module.app)


def test_root_reports_service_and_storage(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "DACMI memory service is running"
    assert payload["storage"].endswith("memories.json")


def test_store_and_query_memory(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    store_response = client.post(
        "/store",
        json={
            "content": "DACMI stores structured memory",
            "tags": ["memory", "stage2"],
            "source": "roadmap",
        },
    )

    assert store_response.status_code == 200
    stored = store_response.json()
    assert stored["content"] == "DACMI stores structured memory"
    assert stored["tags"] == ["memory", "stage2"]
    assert stored["source"] == "roadmap"
    assert stored["id"]
    assert stored["timestamp"]

    query_response = client.get("/query", params={"q": "structured", "tag": "memory"})

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["content"] == "DACMI stores structured memory"


def test_query_filters_by_source(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    client.post(
        "/store",
        json={
            "content": "One note from docs",
            "tags": ["docs"],
            "source": "docs",
        },
    )
    client.post(
        "/store",
        json={
            "content": "One note from chat",
            "tags": ["chat"],
            "source": "chat",
        },
    )

    response = client.get("/query", params={"source": "docs"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["source"] == "docs"
