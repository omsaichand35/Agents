# Deterioration Sentinel Agent

> **Agent type**: ReAct (Reason + Act)
> **Model**: `gemini-2.0-flash`
> **Pattern**: Tool-use loop — reason, call tools, observe, reason again until all patients assessed

---

## The problem it solves

Meena is in Ward 3 at 2 AM. Her temperature went from 37.0 to 37.4 to 37.8 to 38.1
over 12 hours. Her heart rate went from 78 to 103. Her blood pressure dropped from 118
to 96 systolic.

None of these values individually triggered a standard alarm. No nurse flagged it.
No doctor was called. The standard vitals monitoring system saw nothing wrong.

This is early sepsis. In 4–6 hours, Meena will crash.

The Deterioration Sentinel catches this now.

---

## What it does — end to end

```
Every 30 minutes:
  ↓
Read all admitted patients
  ↓
For each patient: fetch last 6 vitals readings
  ↓
Analyse RATE OF CHANGE — not just current values
  ↓
Look for multi-signal patterns:
  • Temp ↑ + HR ↑ + BP ↓ + RR ↑  →  early sepsis
  • SpO2 declining consistently   →  respiratory deterioration
  • BP falling + HR rising        →  haemodynamic compromise
  ↓
Check for existing active alerts (no duplicates)
  ↓
Create alert with FULL reasoning chain  OR  mark patient as stable
  ↓
If patient is marked for discharge: message discharge_negotiator to hold
  ↓
Cycle complete. Sleep 30 minutes.
```

---

## Architecture

```
sentinel_agent.py    ← ReAct loop, model calls, orchestration
sentinel_store.py    ← In-memory patient store (vitals, alerts, messages)
sentinel_tools.py    ← 6 tool definitions + executors
demo.py              ← Single-cycle demo (no sleep)
```

### Tools

| Tool | What it does |
|---|---|
| `read_admitted_patients` | Returns all admitted patients — who to monitor this cycle |
| `read_patient_vitals` | Last 6 readings for one patient — the raw data for analysis |
| `check_active_alerts` | Verify no duplicate alert before creating a new one |
| `create_alert` | Write alert with full reasoning chain — what the doctor reads |
| `message_agent` | Notify another PatientOS agent (e.g. hold a discharge) |
| `no_action` | Explicitly mark a patient stable — always conclude every assessment |

---

## The three synthetic patients

| Patient | Pattern | Expected agent action |
|---|---|---|
| CGH-001 — Meena, 58F | Temp ↑ HR ↑ BP ↓ over 12 hrs — early sepsis | **HIGH alert** |
| CGH-002 — Ravi, 45M  | All vitals stable, minor variation | **No action** |
| CGH-003 — Priya, 32F | SpO2 97→96→95→94 — consistent decline | **MEDIUM alert** |

---

## What makes this genuinely agentic (not automation)

| Automation | This agent |
|---|---|
| Fires when a threshold is crossed | Analyses trend before any threshold is hit |
| Checks one vital at a time | Correlates multiple vitals simultaneously |
| Triggers when told to | Runs continuously, notices situations on its own |
| Returns a flag | Returns a complete reasoning chain explaining WHY |
| One-shot execution | ReAct loop — reasons, acts, observes, reasons again |

---

## Setup

```bash
# Clone
git clone https://github.com/omsaichand35/Agents
cd Agents/agent_3_sentinel

# Install
pip install google-genai

# Set API key (free at https://aistudio.google.com/app/apikey)
export GEMINI_API_KEY='your_key'          # Mac/Linux
$env:GEMINI_API_KEY='your_key'            # Windows PowerShell

# Demo (one cycle, no sleep)
python demo.py

# Full agent (loops every 30 minutes)
python sentinel_agent.py
```

---

## Example output (Meena — early sepsis)

```
[Agent reasoning]
Reading all admitted patients first...

[Tool call] read_admitted_patients({})
[Tool result] { "total_admitted": 3, "patients": [...] }

[Agent reasoning]
Starting with CGH-001 — Meena Krishnan, 58F, Ward 3.
Post-surgical patient. Let me read her vitals trend.

[Tool call] read_patient_vitals({ "patient_id": "CGH-001" })
[Tool result] { "readings": [38.1°C/103bpm/96mmHg, 37.8°C/94bpm/104mmHg, ...] }

[Agent reasoning]
Analysing Meena's trend across 4 readings over 12 hours:
  Temperature  : 37.0 → 37.4 → 37.8 → 38.1  (+1.1°C, consistent rise)
  Heart rate   : 78   → 85   → 94   → 103   (+25 BPM, consistent rise)
  BP systolic  : 118  → 112  → 104  → 96    (-22 mmHg, consistent drop)
Three signals trending simultaneously. This is a classic early sepsis signature —
the body is compensating: HR rising because BP is falling, temp rising with infection.
None of these values individually trigger a standard alarm.
But the PATTERN is unambiguous. Let me check active alerts first.

[Tool call] check_active_alerts({ "patient_id": "CGH-001" })
[Tool result] { "has_active": false }

[Agent reasoning]
No existing alert. Creating HIGH severity alert now.

[Tool call] create_alert({ "patient_id": "CGH-001", "severity": "high", "reasoning": "..." })

  [DETERIORATION ALERT — HIGH]
  Patient  : Meena Krishnan | Ward 3 B-14
  Doctor   : Dr. R. Sharma
```

---

## How it connects to other agents

The `message_agent` tool lets the Sentinel communicate with:

- **discharge_negotiator** — "Hold Meena's discharge, I've flagged deterioration"
- **care_continuity** — "Check if Meena's antibiotics are being administered on schedule"
- **triage_orchestrator** — General queue communications

All agents share the same message bus (the `agent_messages` log in the store).

---

## Production extensions

| Component | Swap with |
|---|---|
| `SentinelStore` | PostgreSQL / hospital EMR (Epic, Cerner) |
| Vitals input | Automatic pull from bedside monitors / nursing system |
| `create_alert` | Push to hospital pager / doctor mobile app |
| `message_agent` | Real inter-agent message queue (Redis, RabbitMQ) |
| Scheduling | AWS EventBridge / Celery beat (every 30 min) |