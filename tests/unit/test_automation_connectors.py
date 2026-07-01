"""External automation connectors — CRM + social (MASTERPLAN_SAAS Step 4).

The CRM connector was a pure echo stub and the social connector was internal-only
(Mongo feed post, no external API). Both now reach external surfaces, mirroring the
existing email/webhook/stripe pattern: outbound HTTP is built by the app and
wrapped in the runtime's `perform_external_call` observability boundary.

`perform_external_call` (runtime-owned observability wrapper) and `urlopen` are
faked here — we assert the app's branch selection, payload/auth construction, and
that outbound calls are correctly wrapped, not the runtime's event emission or real
network I/O. Backward-compatible fallbacks (CRM record-only, social internal-only)
are covered too.
"""

from __future__ import annotations

import json

import pytest

import apps.automation.services.automation_execution_service as aes

pytestmark = pytest.mark.app_profile


class _FakeResp:
    status = 200

    def __init__(self, body: bytes = b'{"ok": true}'):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture
def capture_http(monkeypatch):
    """Fake the runtime external-call wrapper (running the operation) + urlopen."""
    calls: dict[str, list] = {"external": [], "requests": []}

    def fake_perform(*, service_name, db, user_id, endpoint, method, extra, operation):
        calls["external"].append(
            {"service_name": service_name, "endpoint": endpoint, "method": method, "extra": extra}
        )
        return operation()

    def fake_urlopen(req, timeout=None):
        calls["requests"].append(req)
        return _FakeResp()

    monkeypatch.setattr(aes, "perform_external_call", fake_perform)
    monkeypatch.setattr(aes.urllib_request, "urlopen", fake_urlopen)
    return calls


class _FakeInsert:
    inserted_id = "post123"


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def insert_one(self, doc):
        self.docs.append(doc)
        return _FakeInsert()


class _FakeMongo:
    def __init__(self, coll):
        self._coll = coll

    def __getitem__(self, _db_name):
        return {"posts": self._coll}


@pytest.fixture
def fake_mongo(monkeypatch):
    import AINDY.db.mongo_setup as mongo_setup

    coll = _FakeCollection()
    monkeypatch.setattr(mongo_setup, "require_mongo_client", lambda *a, **k: _FakeMongo(coll))
    monkeypatch.setattr(mongo_setup, "MONGO_DB_NAME", "test_db", raising=False)
    return coll


# --------------------------------------------------------------------------- #
# CRM connector
# --------------------------------------------------------------------------- #
def test_crm_records_internally_without_endpoint(capture_http):
    result = aes.execute_automation_action(
        {
            "automation_type": "crm",
            "task_id": 7,
            "automation_config": {"action": "follow_up", "contact": "a@b.com"},
        },
        None,
    )
    assert result["status"] == "recorded"
    assert result["delivery"] == "internal"
    assert result["action"] == "follow_up"
    assert result["contact"] == "a@b.com"
    assert capture_http["external"] == []  # no outbound call was made


def test_crm_posts_to_external_endpoint(capture_http):
    result = aes.execute_automation_action(
        {
            "automation_type": "crm",
            "user_id": "u1",
            "task_name": "Sync lead",
            "automation_config": {
                "endpoint": "https://crm.example.com/contacts",
                "api_key": "secret",
                "action": "upsert",
                "contact": "lead@example.com",
                "details": "post-call note",
            },
        },
        None,
    )
    assert result["status"] == "completed"
    assert result["delivery"] == "external"
    assert result["response"]["status_code"] == 200

    ext = capture_http["external"][0]
    assert ext["service_name"] == "crm"
    assert ext["endpoint"] == "https://crm.example.com/contacts"
    assert ext["method"] == "http.post"

    req = capture_http["requests"][0]
    assert req.full_url == "https://crm.example.com/contacts"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer secret"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent["action"] == "upsert"
    assert sent["contact"] == "lead@example.com"
    assert sent["details"] == "post-call note"


# --------------------------------------------------------------------------- #
# Social connector
# --------------------------------------------------------------------------- #
def test_social_internal_only_without_external_target(capture_http, fake_mongo):
    result = aes.execute_automation_action(
        {
            "automation_type": "social",
            "user_id": "u1",
            "automation_config": {"content": "hello world"},
        },
        None,
    )
    assert result["status"] == "completed"
    assert result["delivery"] == "internal"
    assert result["post_id"] == "post123"
    assert capture_http["external"] == []  # no external publish
    assert fake_mongo.docs[0]["content"] == "hello world"  # internal feed post written


def test_social_also_delivers_externally_when_configured(capture_http, fake_mongo):
    result = aes.execute_automation_action(
        {
            "automation_type": "social",
            "user_id": "u1",
            "automation_config": {
                "content": "launch post",
                "external_endpoint": "https://social.example.com/publish",
                "external_api_key": "tok",
            },
        },
        None,
    )
    assert result["delivery"] == "internal+external"
    assert result["post_id"] == "post123"  # internal feed post still written
    assert result["external_response"]["status_code"] == 200
    assert fake_mongo.docs[0]["content"] == "launch post"

    ext = capture_http["external"][0]
    assert ext["service_name"] == "social"
    assert ext["endpoint"] == "https://social.example.com/publish"

    req = capture_http["requests"][0]
    assert req.get_header("Authorization") == "Bearer tok"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent["content"] == "launch post"


# --------------------------------------------------------------------------- #
# Guards / regression
# --------------------------------------------------------------------------- #
def test_unsupported_automation_type_raises(capture_http):
    with pytest.raises(ValueError, match="unsupported_automation_type"):
        aes.execute_automation_action({"automation_type": "bogus"}, None)


def test_social_requires_content(capture_http, fake_mongo):
    with pytest.raises(ValueError, match="social_content_required"):
        aes.execute_automation_action(
            {"automation_type": "social", "automation_config": {}}, None
        )
