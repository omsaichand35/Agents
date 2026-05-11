"""
tools.py
========
Defines the 4 tools available to the Triage Orchestrator Agent.

  read_queue            — list all patients and their current positions
  read_patient_record   — get full details for one patient
  write_action          — reshuffle queue OR discharge a patient
  send_sms              — send an SMS notification to a patient
  notify_doctor         — send an alert to the on-duty doctor
"""

from __future__ import annotations
from typing import Any
from patient_store import PatientStore

# ── Tool schemas (passed to claude as tools=[...]) ─────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_queue",
        "description": (
            "Returns the current waiting-area queue in token/position order. "
            "Each entry includes patient ID, name, age, token, chief complaint, "
            "position, and time of arrival. Call this at the start of every cycle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_patient_record",
        "description": (
            "Returns the full clinical record for a single patient: "
            "chief complaint, vitals (BP, HR, SpO2, temp), age, and any notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "The patient's unique ID (e.g. P001)",
                }
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "write_action",
        "description": (
            "Perform a queue management action. "
            "action='reshuffle_queue' reorders patients by clinical priority — "
            "supply ordered_patient_ids as a list from highest to lowest acuity. "
            "action='discharge' removes a patient who has been seen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["reshuffle_queue", "discharge"],
                    "description": "The action to perform.",
                },
                "ordered_patient_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "For reshuffle_queue: full ordered list of patient IDs "
                        "from position 1 (next to be seen) to last."
                    ),
                },
                "patient_id": {
                    "type": "string",
                    "description": "For discharge: the patient ID to remove.",
                },
                "reason": {
                    "type": "string",
                    "description": "Clinical justification for this action.",
                },
            },
            "required": ["action", "reason"],
        },
    },
    {
        "name": "send_sms",
        "description": (
            "Send an SMS message to a patient's registered phone number. "
            "Use this to inform patients when their queue position changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Patient ID whose registered number to use.",
                },
                "message": {
                    "type": "string",
                    "description": "The SMS body text (keep under 160 chars).",
                },
            },
            "required": ["patient_id", "message"],
        },
    },
    {
        "name": "notify_doctor",
        "description": (
            "Send an alert to the on-duty doctor. Use when a patient with "
            "acuity score >= 8 is moved to position 1, or any time immediate "
            "clinical attention is required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "priority": {
                    "type": "string",
                    "enum": ["routine", "urgent", "critical"],
                    "description": "Alert priority level.",
                },
                "patient_id": {
                    "type": "string",
                    "description": "The patient requiring attention.",
                },
                "clinical_summary": {
                    "type": "string",
                    "description": (
                        "Brief clinical note for the doctor: patient name, age, "
                        "chief complaint, relevant vitals, and recommended action."
                    ),
                },
            },
            "required": ["priority", "patient_id", "clinical_summary"],
        },
    },
]


# ── Tool executor ──────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict[str, Any], store: PatientStore) -> dict:
    """Route a tool call from the agent to the correct handler."""
    try:
        if name == "read_queue":
            return _read_queue(store)
        elif name == "read_patient_record":
            return _read_patient_record(inputs["patient_id"], store)
        elif name == "write_action":
            return _write_action(inputs, store)
        elif name == "send_sms":
            return _send_sms(inputs["patient_id"], inputs["message"], store)
        elif name == "notify_doctor":
            return _notify_doctor(inputs, store)
        else:
            return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}


# ── Individual tool handlers ───────────────────────────────────────────────

def _read_queue(store: PatientStore) -> dict:
    queue = store.get_queue()
    return {
        "queue_length": len(queue),
        "patients": [
            {
                "patient_id": p.id,
                "name": p.name,
                "age": p.age,
                "token": p.token,
                "position": p.position,
                "chief_complaint": p.chief_complaint,
                "arrived_at": p.arrived_at,
            }
            for p in queue
        ],
    }


def _read_patient_record(patient_id: str, store: PatientStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    return {
        "patient_id": p.id,
        "name": p.name,
        "age": p.age,
        "token": p.token,
        "position": p.position,
        "chief_complaint": p.chief_complaint,
        "arrived_at": p.arrived_at,
        "phone": p.phone,
        "vitals": p.vitals,
        "notes": p.notes,
    }


def _write_action(inputs: dict, store: PatientStore) -> dict:
    action = inputs["action"]
    reason = inputs.get("reason", "")

    if action == "reshuffle_queue":
        ordered_ids = inputs.get("ordered_patient_ids", [])
        if not ordered_ids:
            return {"error": "ordered_patient_ids required for reshuffle_queue"}
        result = store.reshuffle(ordered_ids)
        result["action"] = "reshuffle_queue"
        result["reason"] = reason
        return result

    elif action == "discharge":
        patient_id = inputs.get("patient_id")
        if not patient_id:
            return {"error": "patient_id required for discharge"}
        ok = store.remove_patient(patient_id)
        return {"action": "discharge", "patient_id": patient_id, "success": ok, "reason": reason}

    return {"error": f"Unknown action: {action}"}


def _send_sms(patient_id: str, message: str, store: PatientStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    # In production: call Twilio / AWS SNS here
    store.log_sms(patient_id, p.phone, message)
    print(f"  [SMS -> {p.phone}] {message}")
    return {
        "success": True,
        "patient_id": patient_id,
        "phone": p.phone,
        "message_preview": message[:80],
    }


def _notify_doctor(inputs: dict, store: PatientStore) -> dict:
    priority = inputs["priority"]
    patient_id = inputs["patient_id"]
    summary = inputs["clinical_summary"]

    # In production: push to pager / hospital comms system
    store.log_doctor_notification(summary, priority)
    print(f"\n  [DOCTOR ALERT — {priority.upper()}]\n  {summary}\n")
    return {
        "success": True,
        "priority": priority,
        "patient_id": patient_id,
        "delivered_to": "on_duty_doctor",
    }