# Recovery Guardian Agent

> **Agent type**: ReAct (Reason + Act)
> **Model**: `gemini-2.0-flash`
> **Pattern**: Tool-use loop — reason, call tools, observe, reason again

---

## What it does

Runs every morning. Follows every discharged patient HOME until they are fully recovered.

Each cycle:
1. Reads all patients in post-discharge home recovery
2. Reads their full recovery record — medications, check-in history, recovery day
3. Checks medication compliance log for **silent non-compliance** — patients who say "fine" but are skipping critical drugs
4. Reads their latest check-in response and analyses the trend across all days
5. Takes the right adaptive action for each patient — reminder, routine flag, emergency escalation, or recovery close

---

## The two things that make this genuinely agentic

**1. It catches silent non-compliance.**
Arjun says he feels "better" in every check-in. But he has missed 2 consecutive
mornings of Aspirin and Atorvastatin — critical post-cardiac medications.
A scripted reminder system would never catch this. The agent reads the compliance
log independently, reasons that these are cardiac drugs, and escalates even though
the patient's self-reported feeling is positive.

**2. It reasons before escalating on "worse" responses.**
Meena says "getting worse" on Day 4. The agent does not blindly send an emergency
SMS. It reasons: pneumonia Day 4 with worsening symptoms is unexpected and concerning.
It escalates with a calm, specific instruction, books an appointment, and notifies
the doctor with full clinical context. A Day 1 post-surgery patient saying "worse"
might get a different response — expected discomfort.

---

## Architecture

```
recovery_agent.py    <- ReAct loop, model calls, orchestration
recovery_store.py    <- In-memory store (swap for real DB in prod)
tools.py             <- Tool definitions + executor
demo.py              <- Single-cycle demo (no 24h sleep)
```

### Tools

| Tool | What it does |
|---|---|
| `read_all_patients` | All patients currently in home recovery |
| `read_patient_recovery` | Full discharge record, medications, check-in history |
| `read_compliance_gaps` | Detect missed critical doses silently |
| `send_checkin_sms` | Daily "how are you feeling?" SMS |
| `send_medication_reminder` | Morning/night medicine list with dose and timing |
| `send_emergency_sms` | Urgent SMS to patient + caregiver |
| `notify_doctor` | Alert treating doctor with full clinical context |
| `book_emergency_appointment` | Same-day or next-day urgent slot |
| `mark_patient_recovered` | Close the loop when course is complete |

---

## Three demo patients

| Patient | Scenario | Expected action |
|---|---|---|
| REC-001 Meena (58F) | Day 4 check-in: WORSE. Trend: better->better->same->worse | Emergency SMS + doctor alert + appointment today |
| REC-002 Ravi (45M)  | Day 2 check-in: better. Compliant. Stable. | Medication reminder only |
| REC-003 Arjun (62M) | Check-ins all "better" but missed 2 days critical cardiac meds | Emergency SMS for compliance gap + doctor alert |

---

## Setup

```bash
git clone https://github.com/omsaichand35/Agents
cd Agents/agent_5_recovery

pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here   # free at aistudio.google.com

# Demo (single cycle, no sleep)
python demo.py

# Full agent (runs every 24 hours)
python recovery_agent.py
```

---

## How this fits into PatientOS

```
Agent 1 — Triage Orchestrator    (in-hospital,  every 5 min  — waiting queue)
Agent 2 — Care Continuity        (in-hospital,  every 30 min — medication gaps)
Agent 3 — Deterioration Sentinel (in-hospital,  every 30 min — vitals trends)
Agent 4 — Discharge Negotiator   (in-hospital,  continuous   — discharge planning)
Agent 5 — Recovery Guardian      (post-discharge, every 24h  — home recovery)  <- THIS
```

Agent 5 is the only agent that operates outside the hospital.
It is the bridge between discharge and full recovery — the gap where most
preventable readmissions happen.

---

## Production extensions

| Component | Swap with |
|---|---|
| `RecoveryStore` | PostgreSQL / hospital EMR |
| `send_checkin_sms` | Twilio SMS / WhatsApp Business API |
| `read_compliance_gaps` | Smart pill dispenser IoT feed (e.g. Hero Health) |
| `notify_doctor` | Hospital pager / PagerDuty / Slack |
| `book_emergency_appointment` | Hospital scheduling API |
| Scheduling | AWS EventBridge (8 AM daily) or Celery beat |