"""Load and failure simulation: duplicate webhooks, a flaky CRM, and retries. Run: python -m eval.simulate

We have no real conversion data, so this measures operations (duplicates, retries, alerts), not whether
the scores predict sales.
"""
import json
import random
from collections import Counter

from leads.pipeline import LeadPipeline, replay_pending
from leads.store import LeadStore

COMPANIES = ["acme", "globex", "initech", "umbrella", "hooli", "vandelay"]
TITLES = ["CTO", "Founder", "Analyst", "Director of Ops", "Intern", "VP Marketing"]
SOURCES = ["demo_request", "pricing_page", "webinar", "newsletter"]


def make_leads(n: int, rng: random.Random) -> list[dict]:
    return [{
        "email": f"person{i}@{rng.choice(COMPANIES)}.com" if rng.random() < 0.85 else f"person{i}@gmail.com",
        "first_name": "Lead", "company": rng.choice(COMPANIES), "title": rng.choice(TITLES),
        "company_size": rng.choice([5, 20, 80, 300]), "source": rng.choice(SOURCES),
    } for i in range(n)]


def simulate(fail_rate: float, retries: int, seed: int = 3, n: int = 500) -> dict:
    rng = random.Random(seed)
    leads = make_leads(n, rng)
    # Each lead is delivered 1 to 3 times, as webhook retries do, in random order.
    deliveries = [l for l in leads for _ in range(rng.randint(1, 3))]
    rng.shuffle(deliveries)

    crm_attempts = Counter()
    successful_writes = Counter()  # email -> number of successful CRM writes (should be 1 each)

    def flaky_crm(payload):
        crm_attempts["attempts"] += 1
        if rng.random() < fail_rate:
            return 503, {}
        successful_writes[payload["email"]] += 1
        return 200, {"id": f"c-{payload['email']}"}

    alerts = []
    pipeline = LeadPipeline(crm_upsert=flaky_crm, notify=alerts.append, store=LeadStore(), retries=retries)
    outcomes = Counter()
    for lead in deliveries:
        outcomes[pipeline.process(lead).status] += 1
    # Scheduled replay of the dead-letter queue, as an n8n cron workflow would run it.
    for _ in range(3):
        replay_pending(pipeline)

    alert_counts = Counter(a.split(":")[1].split("(")[0].strip() for a in alerts)
    unique_emails = {l["email"] for l in leads}
    return {
        "unique_leads": len(unique_emails),
        "deliveries": len(deliveries),
        "leads_synced": outcomes["synced"],
        "queued_on_first_failure": outcomes["queued"],
        "unique_leads_never_synced": len(unique_emails - set(successful_writes)),
        "duplicate_crm_writes": sum(c - 1 for c in successful_writes.values() if c > 1),
        "duplicates_suppressed": outcomes["duplicate"],
        "hot_alerts_sent": len(alerts),
        "alert_repeats": sum(c - 1 for c in alert_counts.values() if c > 1),
        "crm_attempts": crm_attempts["attempts"],
    }


if __name__ == "__main__":
    print(json.dumps({
        "CRM fails 30%, 3 retries": simulate(0.30, 3),
        "CRM fails 30%, no retries": simulate(0.30, 0),
        "CRM fails 10%, 3 retries": simulate(0.10, 3),
        "CRM fails 30%, 3 retries, 3 seeds": {f"seed {s}": simulate(0.30, 3, seed=s) for s in (1, 2, 3)},
    }, indent=2))
