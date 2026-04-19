"""
sentinel_tools.py  (updated — real inter-agent communication)
=============================================================
Changes from original:
  • message_agent now publishes to shared_bus.bus instead of local store
  • New process_inbox() handler: sentinel reads its inbox at cycle start
    and acts on messages from other agents (e.g. discharge_cleared, fyi)
  • Tool name kept as "message_agent" for backward compatibility with
    the model's system prompt
"""

from __future__ import annotations
from typing import Any
from datetime import datetime
from sentinel_store import SentinelStore
from shared_bus import bus   # ← real shared bus


TOOL_DEFINITIONS = [
    {
        "name": "read_all_patients",
        "description": (
            "Returns every patient currently admitted to the hospital. "
            "Call this at the start of every monitoring cycle."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_vitals",
        "description": (
            "Fetches the last 6 recorded vitals for a single admitted patient "
            "in chronological order. Analyse TREND — rate of change matters most."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "e.g. CGH-001"}
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "check_active_alerts",
        "description": "Check whether an active deterioration alert already exists for this patient.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "create_deterioration_alert",
        "description": (
            "Create a deterioration alert. The reasoning field is what the doctor reads. "
            "Severity: low | medium | high | critical."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "severity":   {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "reasoning":  {"type": "string"},
            },
            "required": ["patient_id", "severity", "reasoning"],
        },
    },
    {
        "name": "message_agent",
        "description": (
            "Send a structured message to another PatientOS agent via the SHARED MESSAGE BUS. "
            "Available agents: discharge_negotiator, care_continuity, triage_orchestrator. "
            "Message types: hold_discharge, check_medication_gaps, fyi_deterioration, patient_discharged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "enum": ["discharge_negotiator", "care_continuity", "triage_orchestrator"],
                },
                "patient_id":   {"type": "string"},
                "message_type": {
                    "type": "string",
                    "enum": ["hold_discharge", "check_medication_gaps", "fyi_deterioration"],
                },
                "content":   {"type": "string"},
                "priority":  {"type": "string", "enum": ["low", "medium", "high", "critical"],
                              "description": "Default medium. Use high/critical for urgent coordination."},
            },
            "required": ["to_agent", "patient_id", "message_type", "content"],
        },
    },
    {
        "name": "no_action",
        "description": "Explicitly record that a patient is stable — no alert needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "reason":     {"type": "string"},
            },
            "required": ["patient_id", "reason"],
        },
    },
    {
        "name": "process_inbox",
        "description": (
            "Read and act on messages sent to the Deterioration Sentinel by other agents. "
            "Call this at the START of every cycle to avoid duplicate work and respect "
            "decisions made by peer agents (e.g. discharge_cleared means stop monitoring)."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(name: str, inputs: dict[str, Any], store: SentinelStore) -> dict:
    try:
        dispatch = {
            "read_all_patients":          lambda: _read_all_patients(store),
            "read_patient_vitals":        lambda: _read_patient_vitals(inputs["patient_id"], store),
            "check_active_alerts":        lambda: _check_active_alerts(inputs["patient_id"], store),
            "create_deterioration_alert": lambda: _create_alert(inputs, store),
            "message_agent":              lambda: _message_agent(inputs),
            "no_action":                  lambda: _no_action(inputs, store),
            "process_inbox":              lambda: _process_inbox(store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Handlers ───────────────────────────────────────────────────────────────

def _read_all_patients(store: SentinelStore) -> dict:
    patients = store.get_all_patients()
    return {
        "total_admitted": len(patients),
        "patients": [
            {
                "patient_id": p.patient_id, "name": p.name, "age": p.age,
                "ward": p.ward, "bed_number": p.bed_number,
                "attending_doctor": p.attending_doctor,
                "admitted_at": p.admitted_at, "diagnosis": p.diagnosis,
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
        return {"patient_id": patient_id, "patient_name": patient.name,
                "status": "no_vitals_recorded", "readings": []}
    return {
        "patient_id": patient_id, "patient_name": patient.name,
        "age": patient.age, "ward": patient.ward,
        "bed_number": patient.bed_number,
        "attending_doctor": patient.attending_doctor,
        "diagnosis": patient.diagnosis,
        "readings_count": len(readings),
        "readings": [
            {
                "recorded_at": v.recorded_at, "temperature_c": v.temperature,
                "heart_rate_bpm": v.heart_rate, "bp_systolic": v.bp_systolic,
                "bp_diastolic": v.bp_diastolic, "spo2_pct": v.spo2,
                "respiratory_rate": v.respiratory_rate, "recorded_by": v.recorded_by,
            }
            for v in readings
        ],
    }


def _check_active_alerts(patient_id: str, store: SentinelStore) -> dict:
    alerts = store.get_active_alerts(patient_id)
    return {
        "patient_id": patient_id,
        "has_active_alert": len(alerts) > 0,
        "active_alerts": [
            {"alert_id": a.alert_id, "severity": a.severity,
             "triggered_at": a.triggered_at, "status": a.status}
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

    # Automatically notify Care Continuity to check medication gaps for deteriorating patients
    if severity in ("high", "critical"):
        bus.publish(
            from_agent   = "deterioration_sentinel",
            to_agent     = "care_continuity",
            patient_id   = patient_id,
            message_type = "check_medication_gaps",
            content      = (
                f"Deterioration alert {alert.alert_id} ({severity}) fired for "
                f"{patient.name} in {patient.ward}. "
                f"Please verify all critical medications are being administered on schedule. "
                f"Reasoning summary: {reasoning[:120]}"
            ),
            priority = "high" if severity == "high" else "critical",
        )

    print(f"\n  [DETERIORATION ALERT — {severity.upper()}]")
    print(f"  Patient  : {patient.name} ({patient_id}) | {patient.ward} {patient.bed_number}")
    print(f"  Doctor   : {patient.attending_doctor}")
    print(f"  Alert ID : {alert.alert_id}")
    for line in reasoning.split(". "):
        if line.strip():
            print(f"    {line.strip()}.")
    print()

    return {
        "success": True, "alert_id": alert.alert_id,
        "patient_id": patient_id, "patient_name": patient.name,
        "severity": severity, "triggered_at": alert.triggered_at,
        "bus_notification": "care_continuity notified" if severity in ("high", "critical") else "none",
    }


def _message_agent(inputs: dict) -> dict:
    msg = bus.publish(
        from_agent   = "deterioration_sentinel",
        to_agent     = inputs["to_agent"],
        patient_id   = inputs["patient_id"],
        message_type = inputs["message_type"],
        content      = inputs["content"],
        priority     = inputs.get("priority", "medium"),
    )
    return {
        "success": True, "message_id": msg.message_id,
        "from": "deterioration_sentinel", "to": inputs["to_agent"],
        "patient_id": inputs["patient_id"], "sent_at": msg.sent_at,
    }


def _no_action(inputs: dict, store: SentinelStore) -> dict:
    patient_id = inputs["patient_id"]
    reason     = inputs["reason"]
    patient = store.get_patient(patient_id)
    name = patient.name if patient else patient_id
    store._action_log.append({
        "timestamp": datetime.now().isoformat(timespec="minutes"),
        "action": "no_action", "patient_id": patient_id, "reason": reason,
    })
    print(f"  [STABLE] {name} ({patient_id}) — {reason}")
    return {"status": "no_action", "patient_id": patient_id, "patient_name": name, "reason": reason}


def _process_inbox(store: SentinelStore) -> dict:
    """
    Read the sentinel's inbox and act on messages from peer agents.
    Called at the start of every sentinel cycle.
    """
    inbox = bus.get_inbox("deterioration_sentinel", unread_only=True)
    if not inbox:
        return {"messages_found": 0, "actions_taken": []}

    actions = []
    for msg in inbox:
        action_taken = ""

        if msg.message_type == "discharge_cleared":
            # Discharge agent says patient is going home — downgrade monitoring priority
            patient = store.get_patient(msg.patient_id)
            name = patient.name if patient else msg.patient_id
            action_taken = f"Patient {name} discharged — removing from active watch list."
            print(f"  [INBOX] discharge_cleared for {msg.patient_id}: {msg.content[:80]}")

        elif msg.message_type == "fyi":
            # Generic informational — log only
            action_taken = f"FYI logged from {msg.from_agent}: {msg.content[:80]}"
            print(f"  [INBOX] fyi from {msg.from_agent} re {msg.patient_id}: {msg.content[:80]}")

        elif msg.message_type == "high_acuity_alert":
            # Triage found a new high-acuity patient — add to watch list immediately
            action_taken = f"High-acuity flag received from triage for {msg.patient_id}. Will assess vitals next."
            print(f"  [INBOX] high_acuity_alert from triage re {msg.patient_id}: {msg.content[:80]}")

        else:
            action_taken = f"Message type {msg.message_type} logged."

        bus.mark_processed(msg.message_id, response=action_taken)
        actions.append({
            "message_id": msg.message_id,
            "from":       msg.from_agent,
            "type":       msg.message_type,
            "patient_id": msg.patient_id,
            "action":     action_taken,
        })

    return {"messages_found": len(inbox), "actions_taken": actions}