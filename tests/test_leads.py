import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from leads.http import PermanentError, TransientError, call_with_retries
from leads.pipeline import LeadPipeline
from leads.scoring import score_lead

WORKFLOW = Path(__file__).resolve().parent.parent / "n8n" / "lead_to_crm.workflow.json"

HOT = {"email": "cto@acme.io", "title": "CTO", "company_size": 120, "source": "demo_request", "company": "Acme"}
COLD = {"email": "fan@gmail.com", "title": "student", "company_size": 0, "source": "newsletter"}


def test_hot_lead_scores_high_and_explains_itself():
    s = score_lead(HOT)
    assert s.tier == "hot"
    assert s.points == 20 + 25 + 15 + 30
    assert any("senior title" in r for r in s.reasons)


def test_free_email_is_cold():
    assert score_lead(COLD).tier == "cold"


def test_invalid_email_scores_zero():
    assert score_lead({"email": "nope"}).points == 0


def test_retry_recovers_from_transient_error():
    responses = iter([(503, {}), (429, {}), (200, {"id": 7})])
    sleeps = []
    body = call_with_retries(lambda: next(responses), sleep=sleeps.append)
    assert body == {"id": 7}
    assert sleeps == [0.5, 1.0]  # exponential backoff


def test_permanent_error_does_not_retry():
    calls = []

    def send():
        calls.append(1)
        return 422, {"error": "bad"}

    with pytest.raises(PermanentError):
        call_with_retries(send, sleep=lambda s: None)
    assert len(calls) == 1


def test_gives_up_after_max_retries():
    with pytest.raises(TransientError):
        call_with_retries(lambda: (500, {}), retries=2, sleep=lambda s: None)


def test_pipeline_is_idempotent_for_repeated_webhooks():
    upserts = []

    def crm(payload):
        upserts.append(payload)
        return 200, {"id": 42}

    p = LeadPipeline(crm_upsert=crm)
    first = p.process(HOT)
    second = p.process({**HOT, "email": "CTO@ACME.io "})  # same person, different casing and spaces
    assert first.status == "synced"
    assert second.status == "duplicate"
    assert len(upserts) == 1


def test_hot_lead_triggers_alert_once():
    alerts = []
    p = LeadPipeline(crm_upsert=lambda payload: (200, {"id": 1}), notify=alerts.append)
    p.process(HOT)
    p.process(COLD)
    assert len(alerts) == 1 and "cto@acme.io" in alerts[0]


def test_pipeline_rejects_missing_email():
    p = LeadPipeline(crm_upsert=lambda payload: (200, {"id": 1}))
    assert p.process({"email": ""}).status == "rejected"


def test_service_endpoint_requires_secret_and_returns_tier(monkeypatch):
    import app as service

    monkeypatch.setattr(service, "pipeline", LeadPipeline(crm_upsert=lambda p: (200, {"id": "c-1"})))
    client = TestClient(service.app)
    assert client.post("/leads", json=HOT, headers={"x-webhook-secret": "wrong"}).status_code == 401
    resp = client.post("/leads", json=HOT, headers={"x-webhook-secret": service.WEBHOOK_SECRET})
    assert resp.status_code == 200
    assert resp.json()["tier"] == "hot" and resp.json()["crm_contact_id"] == "c-1"


def test_n8n_workflow_is_valid_and_connected():
    wf = json.loads(WORKFLOW.read_text())
    names = {n["name"] for n in wf["nodes"]}
    assert {"Lead Webhook", "Score and Sync to CRM", "Is Hot Lead?", "Alert Sales on Slack"} <= names
    for source, outputs in wf["connections"].items():
        assert source in names
        for branch in outputs["main"]:
            for link in branch:
                assert link["node"] in names
    assert all(n.get("id") for n in wf["nodes"])


def test_lead_is_queued_not_dropped_when_crm_is_down(tmp_path):
    from leads.pipeline import replay_pending
    from leads.store import LeadStore

    state = {"up": False}

    def crm(payload):
        return (200, {"id": 9}) if state["up"] else (503, {})

    store = LeadStore(tmp_path / "leads.db")
    p = LeadPipeline(crm_upsert=crm, store=store, retries=1)
    assert p.process(HOT).status == "queued"
    assert len(store.pending()) == 1
    state["up"] = True
    assert replay_pending(p) == 1
    assert store.pending() == []
    assert store.get(HOT["email"]) == "9"


def test_dedupe_survives_restart(tmp_path):
    from leads.store import LeadStore

    path = tmp_path / "leads.db"
    writes = []

    def crm(payload):
        writes.append(payload)
        return 200, {"id": 1}

    LeadPipeline(crm_upsert=crm, store=LeadStore(path)).process(HOT)
    restarted = LeadPipeline(crm_upsert=crm, store=LeadStore(path))  # a new process, same database
    assert restarted.process(HOT).status == "duplicate"
    assert len(writes) == 1


def test_simulation_drains_queue_and_never_duplicates():
    from eval.simulate import simulate

    result = simulate(0.30, 3, seed=1, n=200)
    assert result["unique_leads_never_synced"] == 0
    assert result["duplicate_crm_writes"] == 0
    assert result["alert_repeats"] == 0
