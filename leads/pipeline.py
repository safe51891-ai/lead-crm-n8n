"""Lead pipeline: validate -> score -> upsert to CRM (idempotent) -> alert hot leads once.

CRM and Slack calls are injected, so the pipeline runs offline and can be load-tested with a fake CRM.
"""
from dataclasses import dataclass
from typing import Callable

from leads.http import TransientError, call_with_retries
from leads.scoring import Score, score_lead
from leads.store import LeadStore


@dataclass
class Result:
    status: str                 # "synced" | "duplicate" | "rejected"
    score: Score | None
    crm_contact_id: str | None
    alert: str | None


class LeadPipeline:
    def __init__(self, crm_upsert: Callable[[dict], tuple[int, dict]],
                 notify: Callable[[str], None] | None = None,
                 store: LeadStore | None = None,
                 retries: int = 3,
                 sleep: Callable[[float], None] = lambda s: None):
        self._crm_upsert = crm_upsert
        self._notify = notify
        self._store = store or LeadStore()
        self._retries = retries
        self._sleep = sleep

    def process(self, lead: dict) -> Result:
        email = (lead.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return Result("rejected", None, None, None)

        lead = {**lead, "email": email}
        score = score_lead(lead)

        existing = self._store.get(email)
        if existing:
            return Result("duplicate", score, existing, None)

        payload = {
            "email": email,
            "firstName": lead.get("first_name", ""),
            "companyName": lead.get("company", ""),
            "tags": [f"lead-{score.tier}", f"source-{lead.get('source', 'unknown')}"],
            "customFields": {"lead_score": score.points},
        }
        try:
            body = call_with_retries(lambda: self._crm_upsert(payload), retries=self._retries, sleep=self._sleep)
        except TransientError:
            # The CRM is down for now. Keep the lead, do not drop it; replay_pending() will retry it.
            self._store.queue_failed(email, payload)
            return Result("queued", score, None, None)
        contact_id = str(body.get("id"))
        self._store.clear_queued(email)

        alert = None
        alerted = False
        if score.tier == "hot":
            alert = f"Hot lead: {email} ({lead.get('company', 'unknown company')}), score {score.points}"
            if self._notify:
                self._notify(alert)
                alerted = True
        self._store.save(email, contact_id, alerted)
        return Result("synced", score, contact_id, alert)


def replay_pending(pipeline: LeadPipeline) -> int:
    """Retry queued leads. Returns how many were synced. Run on a schedule (for example an n8n cron node)."""
    synced = 0
    for email, payload in pipeline._store.pending():
        result = pipeline.process({"email": email, "first_name": payload.get("firstName", ""),
                                   "company": payload.get("companyName", ""),
                                   "source": _source_from_tags(payload.get("tags", []))})
        if result.status == "synced":
            synced += 1
    return synced


def _source_from_tags(tags: list[str]) -> str:
    for t in tags:
        if t.startswith("source-"):
            return t[len("source-"):]
    return "unknown"
