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
    assert health.json()["freshness"]["knowledge_verified_at"]
    assert health.json()["ready"] is True
    assert client.get("/index.html").status_code == 200


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers
    assert "strict-transport-security" not in response.headers


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


def test_admin_auth_rejects_non_ascii_header():
    import asyncio
    import backend.app as app_module

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/admin/polling-units",
        "raw_path": b"/api/admin/polling-units",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer caf\xc3\xa9"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    asyncio.run(app_module.app(scope, receive, send))
    assert messages[0]["status"] == 401


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


def test_polling_unit_areas_lists_lgas_and_accepts_state_case(client):
    assert client.post("/api/admin/polling-units", headers=ADMIN, json=_unit(code="AREA/TEST/001")).status_code == 200
    response = client.get("/api/polling-unit-areas", params={"state":"lagos"})
    assert response.status_code == 200
    assert "Ikeja" in response.json()["areas"]


def test_like_wildcards_are_escaped(client):
    assert client.post("/api/admin/polling-units", headers=ADMIN, json=_unit(code="LA/01/04/999")).status_code == 200
    found = client.get("/api/polling-units", params={"state": "%"}).json()
    assert found["count"] == 0


def test_hazard_expiry_uses_timezones(client):
    for hazard in (
        _hazard(
            hazard="already-expired",
            observed_at="2019-01-01T00:00:00+00:00",
            expires_at="2020-01-01T00:00:00+14:00",
        ),
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
    with app_module.db() as con:
        con.execute("DELETE FROM request_rate_limits WHERE endpoint='ask'")
    payload = {"question": "What do I need to bring to vote?", "language": "en"}
    assert client.post("/api/ask", json=payload).status_code == 200
    assert client.post("/api/ask", json=payload).status_code == 200
    assert client.post("/api/ask", json=payload).status_code == 429
    with app_module.db() as con:
        con.execute("DELETE FROM request_rate_limits WHERE endpoint='ask'")


def test_ambiguous_answer_is_declined(client):
    response = client.post(
        "/api/admin/knowledge", headers=ADMIN,
        json={"id":"ambiguous-vote","question":"How do I vote?","answer":"Different answer","language":"en","keywords":["vote"],"source":"INEC","source_url":"https://www.inecnigeria.org/","verified_at":"2026-11-09"},
    )
    assert response.status_code == 200
    answer = client.post("/api/ask", json={"question":"vote","language":"en"}).json()
    assert answer["confidence"] == "low"


def test_polling_units_pagination(client):
    from backend.app import UnitUpload, _unit_row, db

    rows = [_unit_row(UnitUpload(**_unit(code=f"PAGE/{index:03d}", name=f"Page Unit {index:03d}"))) for index in range(3)]
    with db() as con:
        con.executemany("INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    first = client.get("/api/polling-units", params={"state":"Lagos","lga":"Ikeja","ward":"Ward 04","limit":2,"offset":0}).json()
    second = client.get("/api/polling-units", params={"state":"Lagos","lga":"Ikeja","ward":"Ward 04","limit":2,"offset":2}).json()
    assert first["total_count"] >= 3
    assert len(first["results"]) == 2
    assert len(second["results"]) >= 1


def test_whatsapp_body_limit(client, monkeypatch):
    import backend.app as app_module

    monkeypatch.setattr(app_module, "WEBHOOK_MAX_BODY_BYTES", 1)
    response = client.post("/api/webhooks/whatsapp", content="Body=hello")
    assert response.status_code == 413


def test_whatsapp_rejects_non_ascii_signature(monkeypatch):
    import asyncio
    import backend.app as app_module

    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-secret")
    body = b"Body=hello"

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/webhooks/whatsapp",
        "raw_path": b"/api/webhooks/whatsapp",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"x-twilio-signature", b"caf\xc3\xa9"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    asyncio.run(app_module.app(scope, receive, send))
    assert messages[0]["status"] == 403


def test_knowledge_cache_is_invalidated_after_admin_write(client):
    probe = "cacheprobeonly"
    before = client.post("/api/ask", json={"question": probe}).json()
    assert before["confidence"] == "low"

    response = client.post(
        "/api/admin/knowledge",
        headers=ADMIN,
        json={
            "id": "cache-probe",
            "question": "Cache probe question?",
            "answer": "CACHE PROBE ANSWER",
            "language": "en",
            "keywords": [probe],
            "source": "INEC",
            "source_url": "https://www.inecnigeria.org/",
            "verified_at": "2026-11-09",
        },
    )
    assert response.status_code == 200
    assert client.post("/api/ask", json={"question": probe}).json()["answer"] == "CACHE PROBE ANSWER"


def test_seeded_answer_verified_at_is_stable(client):
    import backend.app as app_module

    question = "What do I need to bring to vote?"
    first = client.post("/api/ask", json={"question": question}).json()["citations"][0]["verified_at"]
    app_module.init_db()
    second = client.post("/api/ask", json={"question": question}).json()["citations"][0]["verified_at"]
    assert first == second == app_module.FAQ_VERIFIED_AT


def test_invalid_proximity_radius_uses_default(client, monkeypatch):
    from backend.app import UnitUpload, _unit_row

    unit_payload = _unit(code="RADIUS/TEST/001")
    unit_id = _unit_row(UnitUpload(**unit_payload))[0]
    assert client.post("/api/admin/polling-units", headers=ADMIN, json=unit_payload).status_code == 200

    monkeypatch.setenv("RISK_PROXIMITY_KM", "not-a-number")
    response = client.get(f"/api/polling-units/{unit_id}/risk")
    assert response.status_code == 200
    assert response.json()["proximity_radius_km"] == 10.0


def test_http_client_is_pooled(client):
    import backend.app as app_module

    assert app_module.get_http_client() is app_module.get_http_client()


def test_config_and_health_agree_on_weather(client, monkeypatch):
    monkeypatch.setenv("NIMET_API_KEY", "key-without-endpoint")
    monkeypatch.delenv("NIMET_ENDPOINT", raising=False)
    config = client.get("/api/config").json()
    health = client.get("/api/health").json()
    # Open-Meteo needs no key, so live weather is always available and must be
    # reported consistently by both endpoints.
    assert config["features"]["live_weather"] is True
    assert config["features"]["weather_provider"].startswith("Open-Meteo")
    assert health["integrations"]["open_meteo"] is True
    # NiMet is a separate integration that needs both a key and an endpoint.
    assert health["integrations"]["nimet"] is False


def test_sync_nihsa_does_not_leak_exception(client, monkeypatch):
    import backend.app as app_module

    monkeypatch.setenv("NIHSA_FEED_URL", "https://nihsa.gov.ng/feed")

    async def boom(*args, **kwargs):
        raise app_module.httpx.ReadTimeout("secret-upstream-detail", request=None)

    monkeypatch.setattr(app_module.get_http_client(), "get", boom)
    response = client.post("/api/admin/sync-nihsa", headers=ADMIN)
    assert response.status_code == 502
    assert response.json()["detail"] == "NIHSA feed could not be normalized"
    assert "secret-upstream-detail" not in response.text
