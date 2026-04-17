# Triage Orchestrator Agent

> **Agent type**: ReAct (Reason + Act)  
> **Model**: `claude-sonnet-4-20250514` (Claude Sonnet 4)  
> **Pattern**: Tool-use loop — the agent reasons, calls tools, observes results, reasons again

---

## What it does

Runs 24/7 monitoring the hospital waiting queue. Every 5 minutes it:

1. Reads all patients and their token-assigned positions
2. Fetches each patient's chief complaint and vitals
3. Scores every patient on clinical acuity (1–10)
4. Compares acuity ranking against token order
5. If they don't match — **reshuffles autonomously**
6. Sends SMS to each affected patient explaining the change
7. Alerts the on-duty doctor if a high-acuity patient (score ≥ 8) was moved up

No human approves the queue change. The agent reasons and acts.

---

## Architecture

```
triage_agent.py      ← ReAct loop, model calls, orchestration
patient_store.py     ← In-memory patient DB (swap for real DB in prod)
tools.py             ← Tool definitions + executor
demo.py              ← Single-cycle demo (no sleep)
```

### ReAct loop

```
[User trigger: "Cycle N starting"]
        ↓
  Claude reasons about queue
        ↓
  Tool call: read_queue
        ↓
  Tool call: read_patient_record (per patient)
        ↓
  Agent scores acuity, finds mismatch
        ↓
  Tool call: write_action (reshuffle_queue)
        ↓
  Tool call: send_sms (per affected patient)
        ↓
  Tool call: notify_doctor (if acuity ≥ 8)
        ↓
  Claude: "Cycle complete"  →  stop_reason = end_turn
```

### Tools

| Tool | What it does |
|---|---|
| `read_queue` | Returns all patients in current position order |
| `read_patient_record` | Full clinical record for one patient (vitals, complaint) |
| `write_action` | Reshuffle queue or discharge a patient |
| `send_sms` | SMS a patient about their position change |
| `notify_doctor` | Pager/alert to on-duty doctor |

---

## Acuity scoring guide

| Score | Category | Examples |
|---|---|---|
| 9–10 | Life-threatening | Chest pain + diaphoresis, stroke symptoms (FAST+), severe trauma |
| 7–8 | Urgent | High fever + altered consciousness, severe abdominal pain |
| 5–6 | Moderate | Moderate fever, fractures, moderate pain |
| 1–4 | Low | Minor sprains, mild headache, small lacerations |

---

## Setup

```bash
git clone https://github.com/omsaichand35/Agents
cd Agents

pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...

# Run demo (one cycle, no sleep)
python demo.py

# Run full agent (loops every 5 min)
python triage_agent.py
```

---

## Example output

```
TRIAGE CYCLE 1  |  08:35:00
============================================================

[Agent reasoning]
Reading the queue first to see current token order...

[Tool call] read_queue({})
[Tool result] { "queue_length": 4, "patients": [...] }

[Agent reasoning]
Token order: Ravi S. (A001) → Meena P. (A002) → ...
Meena P. is 70F with chest pain radiating to left arm + diaphoresis.
This is a potential STEMI — acuity 9/10. She must be seen first.
Ravi S. has a sprained ankle — acuity 2/10. Reshuffling.

[Tool call] write_action({ "action": "reshuffle_queue", ... })
[Tool call] send_sms({ "patient_id": "P002", "message": "..." })
[Tool call] send_sms({ "patient_id": "P001", "message": "..." })
[Tool call] notify_doctor({ "priority": "critical", ... })

  [DOCTOR ALERT — CRITICAL]
  Meena P. (70F) moved to slot 1. Chest pain + left arm radiation +
  diaphoresis. Possible STEMI — prep ECG bay immediately.

[Agent] Cycle complete.
```

---

## Production extensions

- Swap `PatientStore` for PostgreSQL / hospital EMR API
- Replace `print` SMS with Twilio or AWS SNS
- Replace `notify_doctor` with hospital pager / Slack / PagerDuty
- Add a FastAPI wrapper to trigger cycles via webhook (new patient check-in)
- Deploy on a cron job or AWS EventBridge (every 5 min)