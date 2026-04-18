# Care Continuity Agent

> **Agent type**: ReAct (Reason + Act)  
> **Model**: `claude-sonnet-4-20250514` (Claude Sonnet 4)  
> **Pattern**: Tool-use loop — reason, call tools, observe, reason again until gap is closed

---

## The problem it solves

A doctor prescribes a critical antibiotic at 10 AM. By 4 PM:
- Pharmacy never dispensed it (out of stock)
- Nurse never administered it
- No human flagged anything

The Care Continuity Agent catches this at its 4 PM cycle. **No human initiated it.**

---

## What it does — end to end

```
Scan all care plans (every 30 min)
  ↓
Detect: Amoxicillin-Clavulanate not dispensed — 6h after prescription, critical drug
  ↓
Query pharmacy → out of stock
  ↓
drug_substitution_search → Co-Amoxiclav 625mg (therapeutically equivalent, in stock)
  ↓
escalate_to_human → Doctor receives one-tap approval request
  ↓
Doctor approves
  ↓
write_action: update_prescription → new med order created
write_action: update_nurse_sheet  → nurse schedule updated with new drug + time
  ↓
send_notification → pharmacy (new order), nurse (updated sheet), doctor (confirmation)
  ↓
Gap resolved. Cycle ends.
```

---

## Architecture

```
care_agent.py    ← ReAct loop, model calls, orchestration
care_store.py    ← In-memory EMR: medications, pharmacy, nurse records, approvals
care_tools.py    ← 7 tool definitions + executors
demo.py          ← Two-cycle demo without 30-min sleep
```

### Tools

| Tool | What it does |
|---|---|
| `scan_care_gaps` | Scans all medications; flags not-dispensed (>2h) and overdue administration (>1h) |
| `read_patient_record` | Full clinical + medication + nurse record for one patient |
| `query_pharmacy` | Stock status + known alternatives for a drug |
| `drug_substitution_search` | Therapeutically equivalent alternatives cross-referenced with live pharmacy stock |
| `escalate_to_human` | One-tap doctor approval request — agent waits for sign-off before acting |
| `write_action` | Update prescription / nurse sheet / mark administered |
| `send_notification` | SMS/pager to doctor, nurse, or pharmacy |

---

## Gap types detected

| Gap type | Trigger | Severity |
|---|---|---|
| `medication_not_dispensed` | Prescribed >2h ago, status still "pending" | Critical if antibiotic/cardiac/anticoagulant |
| `administration_overdue` | Dispensed, nurse record shows "scheduled" >1h past due time | Critical for cardiac drugs |

---

## The human-in-the-loop design

The agent **always calls `escalate_to_human` before substituting a drug**. The doctor receives:
- What drug was prescribed
- Why it can't be given (out of stock)
- The suggested substitute + clinical rationale
- A one-tap approve/reject

Only after approval does the agent call `write_action`. This is the minimal viable human checkpoint — the agent does all the reasoning and preparation; the human provides the single sign-off.

---

## ReAct loop trace

```
[User] Cycle 1 starting. Scan care plans and resolve gaps.

[Agent] I'll start by scanning all active care plans for gaps.
[Tool] scan_care_gaps()
[Result] 2 gaps: MED001 not dispensed (critical), MED003 administration overdue

[Agent] MED001 is a critical antibiotic — 6h since prescription, never dispensed.
        I'll read the patient record first, then query the pharmacy.
[Tool] read_patient_record(P001)
[Tool] query_pharmacy("Amoxicillin-Clavulanate")
[Result] out_of_stock=True, alternatives=["Co-Amoxiclav 625mg", ...]

[Agent] Pharmacy is out of stock. Drug class is beta-lactam antibiotic.
        Searching for therapeutically equivalent alternatives.
[Tool] drug_substitution_search("beta-lactam antibiotic", "Amoxicillin-Clavulanate", "P001")
[Result] Co-Amoxiclav 625mg — in stock, therapeutically equivalent, oral route maintained

[Agent] Co-Amoxiclav 625mg is available and equivalent. Escalating to prescribing doctor.
[Tool] escalate_to_human(patient_id=P001, suggested_action="Substitute Co-Amoxiclav 625mg oral")
[Result] approval_id=APPR-XXXX, status=approved

[Agent] Doctor approved. Updating prescription and nurse schedule.
[Tool] write_action(update_prescription, new_drug="Co-Amoxiclav 625mg")
[Tool] write_action(update_nurse_sheet, new_scheduled_at="now+30min")
[Tool] send_notification(pharmacy, urgent, "New order: Co-Amoxiclav 625mg for P001")
[Tool] send_notification(nurse, urgent, "Updated medication sheet: Co-Amoxiclav replaces Amoxicillin-Clavulanate")
[Tool] send_notification(doctor, routine, "Substitution executed. Nurse notified.")

[Agent] All gaps resolved. Cycle complete.
```

---

## Setup

```bash
# Clone your repo
git clone https://github.com/omsaichand35/Agents
cd Agents

# Install
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Demo (2 cycles, no sleep)
python demo.py

# Full agent (loops every 30 min)
python care_agent.py
```

---

## Production extensions

| Component | Swap with |
|---|---|
| `CareStore` | Epic EMR API / Cerner FHIR API |
| `query_pharmacy` | Hospital pharmacy management system (Pyxis, Omnicell) |
| `drug_substitution_search` | Lexicomp / Micromedex / RxNorm API |
| `escalate_to_human` | Mobile pager app with push notification + approval button |
| `send_notification` | Twilio SMS / PagerDuty / hospital internal comms |
| Scheduling | AWS EventBridge rule (every 30 min) or Celery beat |