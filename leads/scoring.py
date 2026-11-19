"""Score an inbound lead. Rules first (explainable, testable); an LLM can refine the score later."""
from dataclasses import dataclass, field

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}
SENIOR_TITLES = ("ceo", "cto", "cfo", "founder", "head", "director", "vp", "owner")
HIGH_INTENT_SOURCES = {"demo_request": 30, "pricing_page": 20, "webinar": 10, "newsletter": 0}


@dataclass
class Score:
    points: int
    tier: str                      # "hot" | "warm" | "cold"
    reasons: list[str] = field(default_factory=list)


def score_lead(lead: dict) -> Score:
    points, reasons = 0, []

    email = lead.get("email", "")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if not domain:
        return Score(0, "cold", ["invalid email"])
    if domain not in FREE_EMAIL_DOMAINS:
        points += 20
        reasons.append("business email domain (+20)")

    title = lead.get("title", "").lower()
    if any(t in title for t in SENIOR_TITLES):
        points += 25
        reasons.append("senior title (+25)")

    employees = int(lead.get("company_size") or 0)
    if employees >= 50:
        points += 15
        reasons.append("company size 50+ (+15)")

    source = lead.get("source", "")
    intent = HIGH_INTENT_SOURCES.get(source, 0)
    if intent:
        points += intent
        reasons.append(f"source {source} (+{intent})")

    tier = "hot" if points >= 60 else "warm" if points >= 30 else "cold"
    return Score(points, tier, reasons)
