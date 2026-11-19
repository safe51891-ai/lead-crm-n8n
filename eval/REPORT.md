# Lead Pipeline: Reliability Report

Simulation (`eval/simulate.py`): 500 unique leads, each delivered 1 to 3 times (webhook retries), against a CRM that fails a random share of calls with 503. Results are from `eval/SIMULATION.json`.

| Scenario | Unique leads never in CRM | Duplicate CRM writes | Duplicate alerts |
|---|---|---|---|
| CRM fails 10%, 3 retries | 0 | 0 | 0 |
| CRM fails 30%, 3 retries | 0 (after dead-letter replay) | 0 | 0 |
| CRM fails 30%, no retries | 2 (after 3 replay passes) | 0 | 0 |

Across three random seeds at 30% failure with retries, every lead reached the CRM after replay.

## What this shows
- Duplicate webhook deliveries never create a second contact or a second Slack alert.
- Retries recover most transient failures. The dead-letter queue catches the rest. Without it, 30% failures lost leads.
- A restart does not reset duplicate protection, because the store is a database.

## What this does not show
- **Scoring accuracy.** There is no real conversion data here. The scoring weights are my rules, not learned from outcomes. Test them against real sales results before trusting the "hot" tier.
- **Real CRM behavior.** The CRM is simulated with random 503 errors. Real APIs also rate-limit (429), return partial failures, and change their contact schema.
- **Replay limits.** The simulation replays only three times. Production replay should run on a schedule and alert when a lead has been queued for hours.
