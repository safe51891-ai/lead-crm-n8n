"""Service called by the n8n workflow. Run: uvicorn app:app --reload

Set CRM_API_KEY and SLACK_WEBHOOK_URL in the environment for real calls. Without them the service runs in dry-run mode.
"""
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from leads.pipeline import LeadPipeline
from leads.store import LeadStore


class Lead(BaseModel):
    email: str
    first_name: str = ""
    company: str = ""
    title: str = ""
    company_size: int = 0
    source: str = "newsletter"


def _dry_run_crm(payload: dict) -> tuple[int, dict]:
    # Replace with an httpx call to the CRM upsert endpoint, using CRM_API_KEY as a Bearer token.
    return 200, {"id": f"dry-{abs(hash(payload['email'])) % 10_000}"}


pipeline = LeadPipeline(crm_upsert=_dry_run_crm, notify=None, store=LeadStore(os.getenv("LEAD_DB", "leads.db")))
app = FastAPI(title="Lead to CRM")
WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "dev-secret")


@app.post("/leads")
def ingest(lead: Lead, x_webhook_secret: str = Header(...)):
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")
    result = pipeline.process(lead.model_dump())
    if result.status == "rejected":
        raise HTTPException(status_code=422, detail="invalid email")
    return {
        "status": result.status,
        "tier": result.score.tier if result.score else None,
        "score": result.score.points if result.score else None,
        "reasons": result.score.reasons if result.score else [],
        "crm_contact_id": result.crm_contact_id,
        "alert": result.alert,
    }
