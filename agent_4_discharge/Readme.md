# Discharge Negotiator Agent

> **Agent type**: ReAct (Reason + Act)
> **Model**: `gemini-2.5-flash`
> **Pattern**: Tool-use loop — reason, call tools, observe, reason again until all blockers cleared

## The problem it solves

Ravi is medically ready for discharge. Vitals stable 48h. Doctor cleared him. But no one:
- Wrote the discharge summary
- Submitted the insurance pre-authorisation
- Told the pharmacy to prepare take-home medications
- Contacted his family about transport

The Discharge Negotiator Agent catches all of this. **No human initiated it.**

## Architecture

```
discharge_agent.py    ← ReAct loop, model calls, orchestration
discharge_store.py    ← In-memory store: patients, blockers, insurance, summaries
discharge_tools.py    ← 10 tool definitions + executors
demo.py               ← Single-cycle demo (no sleep)
demo_ollama.py        ← Same demo via local Ollama (qwen2.5:7b)
```

## Setup

```bash
pip install google-genai
export GEMINI_API_KEY='your_key'
python demo.py
```

## Tools

| Tool | What it does |
|---|---|
| `get_discharge_candidates` | Scan all patients — ready or not, how many blockers |
| `read_patient_record` | Full record: diagnosis, ICD-10, insurance, blocker list |
| `check_blocker_status` | All blockers and their state (pending / resolved) |
| `draft_discharge_summary` | Auto-generate summary, send to doctor for e-signature |
| `submit_insurance_preauth` | Submit pre-auth with ICD-10 codes, returns auth number |
| `message_agent` | Coordinate with pharmacy, sentinel, triage agents |
| `send_sms` | SMS patient or family |
| `resolve_blocker` | Mark a blocker resolved |
| `update_discharge_eta` | Set or revise estimated discharge time |
| `no_action` | Record patient is not ready yet |