"""
tools.py
========
Tool definitions and executors for the Deterioration Sentinel Agent.

Follows the exact same pattern as:
  agent_1_triage/tools.py      — TOOL_DEFINITIONS list + execute_tool()
  agent_2_caretaker/care_tools.py

Tools:
  read_all_patients       — list every admitted patient the agent must watch
  read_patient_vitals     — fetch last N readings for one patient
  check_active_alerts     — prevent duplicate alerts for same patient
  create_deterioration_alert  — write alert with full reasoning chain
  message_agent           — notify another PatientOS agent
  no_action               — explicitly record "stable, no action needed"
"""

from __future__ import annotations
from typing import Any
from datetime import datetime
from sentinel_store import SentinelStore, DeteriorationAlert

# ── Tool schemas (passed to Gemini as function_declarations) ───────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_all_patients",
        "description": (
            "Returns every patient currently admitted to the hospital. "
            "Call this at the start of every monitoring cycle to get the full "
            "list of patients the agent must assess. Each entry includes patient_id, "
            "name, age, ward, bed_number, attending_doctor, and diagnosis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_patient_vitals",
        "description": (
            "Fetches the last 6 recorded vitals for a single admitted patient. "
            "Returns readings in chronological order (oldest first) so you can "
            "analyse the TREND — rate of change is more important than any single value. "
            "Each reading includes: recorded_at, temperature (°C), heart_rate (BPM), "
            "bp_systolic (mmHg), bp_diastolic (mmHg), spo2 (%), respiratory_rate, recorded_by."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The patient's unique ID e.g. CGH-001",
                }
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "check_active_alerts",
        "description": (
            "Check whether an active deterioration alert already exists for this patient. "
            "Always call this BEFORE creating a new alert to avoid duplicate escalations. "
            "Returns has_active_alert (bool) and the list of existing active alerts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient ID to check",
                }
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "create_deterioration_alert",
        "description": (
            "Create a deterioration alert for a patient. "
            "Only call this when you have analysed the vitals trend and found a genuine "
            "multi-signal deterioration pattern. "
            "The reasoning field is critical — it must contain your full chain-of-thought: "
            "which signals changed, by how much, over what time period, what pattern this "
            "resembles (e.g. early sepsis), and what you recommend. "
            "The doctor will read this reasoning to make a clinical decision. Be precise.\n\n"
            "Severity guide:\n"
            "  low      — 1-2 signals trending mildly, patient stable overall\n"
            "  medium   — 2-3 signals trending, rate of change concerning\n"
            "  high     — 3+ signals trending simultaneously OR fast rate of change\n"
            "  critical — Classic multi-signal sepsis pattern OR SpO2 below 93%"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient ID",
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Alert severity level",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Your complete reasoning chain. Must include: "
                        "1) Exact vital values and timestamps, "
                        "2) Rate of change for each signal, "
                        "3) Which pattern this resembles, "
                        "4) Clinical recommendation, "
                        "5) Why you chose this severity. "
                        "This is what the doctor reads. Make it count."
                    ),
                },
            },
            "required": ["patient_id", "severity", "reasoning"],
        },
    },
    {
        "name": "message_agent",
        "description": (
            "Send a structured message to another PatientOS agent via the message bus. "
            "Use this to coordinate with other agents — for example: "
            "message the discharge_negotiator to hold a patient's discharge when you flag them, "
            "or message the care_continuity agent to check medication gaps for a deteriorating patient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "enum": ["discharge_negotiator", "care_continuity", "triage_orchestrator"],
                    "description": "Target agent to message",
                },
                "patient_id": {
                    "type": "string",
                    "description": "Patient this message concerns",
                },
                "message_type": {
                    "type": "string",
                    "enum": ["hold_discharge", "check_medication_gaps", "fyi_deterioration"],
                    "description": "Type of inter-agent message",
                },
                "content": {
                    "type": "string",
                    "description": "Plain-text message content for the receiving agent",
                },
            },
            "required": ["to_agent", "patient_id", "message_type", "content"],
        },
    },
    {
        "name": "no_action",
        "description": (
            "Call this when you have fully assessed a patient's vitals and determined "
            "that NO deterioration alert is needed. "
            "This explicitly records your assessment so the audit log is complete. "
            "Provide a brief reason explaining why the patient is stable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient you assessed",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Brief explanation of why no action is needed — "
                        "e.g. 'All vitals stable across 4 readings. No trending pattern detected.'"
                    ),
                },
            },
            "required": ["patient_id", "reason"],
        },
    },
]


# ── Tool executor ──────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict[str, Any], store: SentinelStore) -> dict:
    """Route a tool call from the agent to the correct handler."""
    try:
        dispatch = {
            "read_all_patients":          lambda: _read_all_patients(store),
            "read_patient_vitals":        lambda: _read_patient_vitals(inputs["patient_id"], store),
            "check_active_alerts":        lambda: _check_active_alerts(inputs["patient_id"], store),
            "create_deterioration_alert": lambda: _create_alert(inputs, store),
            "message_agent":              lambda: _message_agent(inputs, store),
            "no_action":                  lambda: _no_action(inputs, store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Individual handlers ────────────────────────────────────────────────────

def _read_all_patients(store: SentinelStore) -> dict:
    patients = store.get_all_patients()
    return {
        "total_admitted": len(patients),
        "patients": [
            {
                "patient_id":       p.patient_id,
                "name":             p.name,
                "age":              p.age,
                "ward":             p.ward,
                "bed_number":       p.bed_number,
                "attending_doctor": p.attending_doctor,
                "admitted_at":      p.admitted_at,
                "diagnosis":        p.diagnosis,
            }
            for p in patients
        ],
    }


def _read_patient_vitals(patient_id: str, store: SentinelStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    readings = store.get_vitals(patient_id, last_n=6)
    if not readings:
        return {
            "patient_id":   patient_id,
            "patient_name": patient.name,
            "status":       "no_vitals_recorded",
            "readings":     [],
        }

    return {
        "patient_id":       patient_id,
        "patient_name":     patient.name,
        "age":              patient.age,
        "ward":             patient.ward,
        "bed_number":       patient.bed_number,
        "attending_doctor": patient.attending_doctor,
        "diagnosis":        patient.diagnosis,
        "readings_count":   len(readings),
        "readings": [
            {
                "recorded_at":     v.recorded_at,
                "temperature_c":   v.temperature,
                "heart_rate_bpm":  v.heart_rate,
                "bp_systolic":     v.bp_systolic,
                "bp_diastolic":    v.bp_diastolic,
                "spo2_pct":        v.spo2,
                "respiratory_rate": v.respiratory_rate,
                "recorded_by":     v.recorded_by,
            }
            for v in readings
        ],
    }


def _check_active_alerts(patient_id: str, store: SentinelStore) -> dict:
    alerts = store.get_active_alerts(patient_id)
    return {
        "patient_id":       patient_id,
        "has_active_alert": len(alerts) > 0,
        "active_alerts": [
            {
                "alert_id":    a.alert_id,
                "severity":    a.severity,
                "triggered_at": a.triggered_at,
                "status":      a.status,
            }
            for a in alerts
        ],
    }


def _create_alert(inputs: dict, store: SentinelStore) -> dict:
    patient_id = inputs["patient_id"]
    severity   = inputs["severity"]
    reasoning  = inputs["reasoning"]

    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    alert = store.create_alert(patient_id, severity, reasoning)

    # Print formatted alert (mirrors Agent 1/2 doctor notification style)
    print(f"\n  [DETERIORATION ALERT — {severity.upper()}]")
    print(f"  Patient  : {patient.name} ({patient_id}) | {patient.ward} {patient.bed_number}")
    print(f"  Doctor   : {patient.attending_doctor}")
    print(f"  Alert ID : {alert.alert_id}")
    print(f"  Reasoning:\n")
    for line in reasoning.split(". "):
        if line.strip():
            print(f"    {line.strip()}.")
    print()

    return {
        "success":      True,
        "alert_id":     alert.alert_id,
        "patient_id":   patient_id,
        "patient_name": patient.name,
        "severity":     severity,
        "triggered_at": alert.triggered_at,
        "message":      f"Alert {alert.alert_id} created. {patient.attending_doctor} notified.",
    }


def _message_agent(inputs: dict, store: SentinelStore) -> dict:
    to_agent     = inputs["to_agent"]
    patient_id   = inputs["patient_id"]
    message_type = inputs["message_type"]
    content      = inputs["content"]

    msg = store.send_agent_message(to_agent, patient_id, message_type, content)

    print(f"  [AGENT MSG → {to_agent}] {content[:100]}")

    return {
        "success":    True,
        "message_id": msg.message_id,
        "from":       "deterioration_sentinel",
        "to":         to_agent,
        "patient_id": patient_id,
        "sent_at":    msg.sent_at,
    }


def _no_action(inputs: dict, store: SentinelStore) -> dict:
    patient_id = inputs["patient_id"]
    reason     = inputs["reason"]

    patient = store.get_patient(patient_id)
    name    = patient.name if patient else patient_id

    store._action_log.append({
        "timestamp":  datetime.now().isoformat(timespec="minutes"),
        "action":     "no_action",
        "patient_id": patient_id,
        "reason":     reason,
    })

    print(f"  [STABLE] {name} ({patient_id}) — {reason}")

    return {
        "status":     "no_action",
        "patient_id": patient_id,
        "patient_name": name,
        "reason":     reason,
    }