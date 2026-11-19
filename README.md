# Lead-to-CRM Automation (n8n + Python service)

An inbound lead (form, webhook, LinkedIn campaign) is validated, scored, synced to the CRM without duplicates, and, if it is hot, announced to sales on Slack.

## Parts
- **n8n workflow** (`n8n/lead_to_crm.workflow.json`): Webhook → Score and Sync (HTTP, 3 retries, error output) → IF hot → Slack. Import it into n8n and set `LEAD_SERVICE_URL`, `N8N_WEBHOOK_SECRET`, and `SLACK_WEBHOOK_URL` in n8n's environment.
- **Python service** (`app.py`): the scoring and sync logic, so the rules are testable outside n8n.
- **Scoring** (`leads/scoring.py`): explainable points (business domain, senior title, company size, intent source), with the reasons returned.
- **Resilient calls** (`leads/http.py`): retries 429 and 5xx with exponential backoff, and fails fast on 4xx.
- **Dead-letter queue** (`leads/store.py`, `replay_pending`): a lead the CRM rejects for now is queued, not dropped.
- **Durable store** (`leads/store.py`): duplicate protection survives restarts.
- **Pipeline** (`leads/pipeline.py`): normalizes email, skips duplicates (idempotent for webhook retries), and alerts once per hot lead.

## Measured reliability (eval/REPORT.md)
- Duplicate CRM writes and duplicate alerts: **0** in every scenario.
- At a 30% CRM failure rate, retries plus the dead-letter queue leave **0** leads unsynced after replay (three seeds). Without retries, 2 of 500 remain.
- Scoring accuracy is **not measured**: there is no real conversion data here.

## Run
```bash
pip install -r requirements.txt
pytest -q                          # 11 tests, offline
uvicorn app:app --reload           # POST /leads with header x-webhook-secret
```

## Production notes
- Replace `_dry_run_crm` in `app.py` with a real httpx call to the CRM upsert endpoint. Use HubSpot or GoHighLevel's documented contact-upsert API, with the key in an environment variable.
- The duplicate guard is in memory. Move it to a database table (or use the CRM's own upsert by email) so it survives restarts.
- Check the n8n Slack node's parameters in your n8n version. The workflow JSON is structurally valid and tested, but the Slack credential must be created in n8n.
