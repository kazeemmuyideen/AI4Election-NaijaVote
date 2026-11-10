import pytest
from fastapi.testclient import TestClient

from backend.app import app

ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _unit(**overrides):
    payload = {
        "state": "Lagos",
        "lga": "Ikeja",
        "ward": "Ward 04",
        "name": "Test Polling Unit",
        "code": "LA/01/04/001",
        "latitude": 6.6,
        "longitude": 3.35,
        "source": "INEC",
        "source_url": "https://www.inecnigeria.org/",
        "verified_at": "2026-11-09",
    }
    payload.update(overrides)
    return payload


def _hazard(**overrides):
    payload = {
        "state": "ExpiryState",
        "hazard": "flood",
        "severity": 80,
        "details": "Flooding on the access road",
        "source": "NIHSA",
        "source_url": "https://nihsa.gov.ng/",
        "observed_at": "2026-11-10T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_health_and_index(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["data"]["knowledge"] >= 7
    assert client.get("/index.html").status_code == 200


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers


def test_ask_returns_cited_answer(client):
    body = client.post("/api/ask", json={"question": "What do I need to bring to vote?", "language": "en"}).json()
    assert body["confidence"] == "high"
    assert body["citations"][0]["url"].startswith("https://")


def test_unrelated_question_declines(client):
    body = client.post("/api/ask", json={"question": "I sold my gold", "language": "en"}).json()
    assert body["confidence"] == "low"
    assert "don’t have a verified answer" in body["answer"]


def test_retrieval_respects_language(client):
    response = client.post(
        "/api/admin/knowledge",
        headers=ADMIN,
        json={
            "id": "ha-test",
            "question": "Me zan kawo?",
            "answer": "HAUSA ANSWER ONLY",
            "language": "ha",
            "keywords": ["need", "bring", "vote"],
            "source": "INEC",
            "source_url": "https://www.inecnigeria.org/",
            "verified_at": "2026-11-09",
        },
    )
    assert response.status_code == 200

    english = client.post("/api/ask", json={"question": "What do I need to bring to vote?", "language": "en"}).json()
    assert english["language"] == "en"

    hausa = client.post("/api/ask", json={"question": "need bring vote", "language": "ha"}).json()
    assert hausa["language"] == "ha"
    assert hausa["answer"] == "HAUSA ANSWER ONLY"


def test_admin_auth_runs_before_body_validation(client):
    assert client.post("/api/admin/polling-units", json={}).status_code == 401


def test_import_rejects_non_https_source(client):
    csv = (
        "state,lga,ward,name,code,source,source_url,verified_at\n"
        "Lagos,Ikeja,Ward 04,Test,C,INEC,http://insecure.example,2026-11-09\n"
    )
    response = client.post(
        "/api/admin/import-polling-units",
        headers={**ADMIN, "Content-Type": "text/csv"},
        content=csv,
    )
    assert response.status_code == 400


def test_import_rejects_empty_required_fields(client):
    csv = "state,lga,ward,name,code,source,source_url,verified_at\n,,,,,INEC,https://x.example,2026-11-09\n"
    response = client.post(
        "/api/admin/import-polling-units",
        headers={**ADMIN, "Content-Type": "text/csv"},
        content=csv,
    )
    assert response.status_code == 400


def test_import_and_search_polling_unit(client):
    csv = (
        "state,lga,ward,name,code,source,source_url,verified_at\n"
        "Lagos,Ikeja,Ward 04,Imported Unit,LA/01/04/002,INEC,https://www.inecnigeria.org/,2026-11-09\n"
    )
    response = client.post(
        "/api/admin/import-polling-units",
        headers={**ADMIN, "Content-Type": "text/csv"},
        content=csv,
    )
    assert response.json() == {"imported": 1}

    found = client.get("/api/polling-units", params={"state": "Lagos", "lga": "Ikeja"}).json()
    assert any(unit["code"] == "LA/01/04/002" for unit in found["results"])


def test_like_wildcards_are_escaped(client):
    assert client.post("/api/admin/polling-units", headers=ADMIN, json=_unit(code="LA/01/04/999")).status_code == 200
    found = client.get("/api/polling-units", params={"state": "%"}).json()
    assert found["count"] == 0


def test_hazard_expiry_uses_timezones(client):
    for hazard in (
        _hazard(hazard="already-expired", expires_at="2020-01-01T00:00:00+14:00"),
        _hazard(hazard="still-active", expires_at="2099-01-01T00:00:00+00:00"),
    ):
        assert client.post("/api/admin/hazards", headers=ADMIN, json=hazard).status_code == 200

    body = client.get("/api/risk", params={"state": "ExpiryState"}).json()
    assert [alert["hazard"] for alert in body["alerts"]] == ["still-active"]


def test_invalid_hazard_date_is_rejected(client):
    response = client.post("/api/admin/hazards", headers=ADMIN, json=_hazard(observed_at="not-a-date"))
    assert response.status_code == 422


def test_ask_is_rate_limited(client, monkeypatch):
    import backend.app as app_module

    monkeypatch.setattr(app_module, "ASK_RATE_LIMIT", 2)
    app_module._RATE_BUCKETS.clear()
    payload = {"question": "What do I need to bring to vote?", "language": "en"}
    assert client.post("/api/ask", json=payload).status_code == 200
    assert client.post("/api/ask", json=payload).status_code == 200
    assert client.post("/api/ask", json=payload).status_code == 429
    app_module._RATE_BUCKETS.clear()


def test_config_and_health_agree_on_weather(client, monkeypatch):
    monkeypatch.setenv("NIMET_API_KEY", "key-without-endpoint")
    monkeypatch.delenv("NIMET_ENDPOINT", raising=False)
    assert client.get("/api/config").json()["features"]["live_weather"] is False
    assert client.get("/api/health").json()["integrations"]["nimet"] is False
