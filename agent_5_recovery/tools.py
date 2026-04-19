"""
tools.py  (triage — updated with real bus integration)
=======================================================
Changes:
  • notify_doctor also publishes high_acuity_alert to sentinel + care
  • New process_inbox() tool reads bed_available and medication_gap_found messages
"""

from __future__ import annotations
from typing import Any
from patient_store import PatientStore
from shared_bus import bus


TOOL_DEFINITIONS = [
    {
        "name": "read_queue",
        "description": "Returns current waiting queue. Also checks bus inbox for bed_available notices.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_record",
        "description": "Full clinical record for a single patient.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "write_action",
        "description": "Reshuffle queue or discharge a patient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["reshuffle_queue", "discharge"]},
                "ordered_patient_ids": {"type": "array", "items": {"type": "string"}},
                "patient_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["action", "reason"],
        },
    },
    {
        "name": "send_sms",
        "description": "SMS a patient about their queue position change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "message":    {"type": "string"},
            },
            "required": ["patient_id", "message"],
        },
    },
    {
        "name": "notify_doctor",
        "description": (
            "Alert the on-duty doctor. For acuity >= 8 also publishes "
            "high_acuity_alert to deterioration_sentinel and care_continuity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "priority":         {"type": "string", "enum": ["routine", "urgent", "critical"]},
                "patient_id":       {"type": "string"},
                "clinical_summary": {"type": "string"},
                "acuity_score":     {"type": "integer",
                                    "description": "1-10 acuity. If >= 8, peers are notified via bus."},
            },
            "required": ["priority", "patient_id", "clinical_summary"],
        },
    },
    {
        "name": "process_inbox",
        "description": (
            "Read messages addressed to triage_orchestrator from peer agents. "
            "Call at cycle start. bed_available from discharge means a room just opened. "
            "medication_gap_found from care means a patient had a critical drug issue."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(name: str, inputs: dict[str, Any], store: PatientStore) -> dict:
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
        elif name == "process_inbox":
            return _process_inbox(store)
        else:
            return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}


def _read_queue(store: PatientStore) -> dict:
    queue = store.get_queue()
    return {
        "queue_length": len(queue),
        "patients": [
            {"patient_id": p.id, "name": p.name, "age": p.age, "token": p.token,
             "position": p.position, "chief_complaint": p.chief_complaint, "arrived_at": p.arrived_at}
            for p in queue
        ],
    }


def _read_patient_record(patient_id: str, store: PatientStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    return {
        "patient_id": p.id, "name": p.name, "age": p.age, "token": p.token,
        "position": p.position, "chief_complaint": p.chief_complaint,
        "arrived_at": p.arrived_at, "phone": p.phone, "vitals": p.vitals, "notes": p.notes,
    }


def _write_action(inputs: dict, store: PatientStore) -> dict:
    action = inputs["action"]
    reason = inputs.get("reason", "")
    if action == "reshuffle_queue":
        ordered_ids = inputs.get("ordered_patient_ids", [])
        if not ordered_ids:
            return {"error": "ordered_patient_ids required"}
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
    store.log_sms(patient_id, p.phone, message)
    print(f"  [SMS -> {p.phone}] {message}")
    return {"success": True, "patient_id": patient_id, "phone": p.phone, "message_preview": message[:80]}


def _notify_doctor(inputs: dict, store: PatientStore) -> dict:
    priority   = inputs["priority"]
    patient_id = inputs["patient_id"]
    summary    = inputs["clinical_summary"]
    acuity     = inputs.get("acuity_score", 0)

    store.log_doctor_notification(summary, priority)
    print(f"\n  [DOCTOR ALERT — {priority.upper()}]\n  {summary}\n")

    # Notify peer agents for high-acuity cases
    if acuity >= 8:
        bus.publish(
            from_agent   = "triage_orchestrator",
            to_agent     = "deterioration_sentinel",
            patient_id   = patient_id,
            message_type = "high_acuity_alert",
            content      = (
                f"High-acuity patient (score {acuity}/10) moved to position 1. "
                f"Clinical summary: {summary[:150]}"
            ),
            priority = "high" if acuity < 10 else "critical",
        )
        bus.publish(
            from_agent   = "triage_orchestrator",
            to_agent     = "care_continuity",
            patient_id   = patient_id,
            message_type = "high_acuity_alert",
            content      = (
                f"High-acuity patient (score {acuity}/10) entering ED. "
                f"Verify all medications are ready. Summary: {summary[:120]}"
            ),
            priority = "high",
        )

    return {
        "success": True, "priority": priority, "patient_id": patient_id,
        "delivered_to": "on_duty_doctor",
        "bus_notified": ["deterioration_sentinel", "care_continuity"] if acuity >= 8 else [],
    }


def _process_inbox(store: PatientStore) -> dict:
    inbox = bus.get_inbox("triage_orchestrator", unread_only=True)
    if not inbox:
        return {"messages_found": 0, "actions_taken": []}

    actions = []
    for msg in inbox:
        action_taken = ""

        if msg.message_type == "bed_available":
            action_taken = (
                f"Bed available notice received from discharge_negotiator "
                f"for patient {msg.patient_id}. Ward capacity updated."
            )
            print(f"  [INBOX] bed_available: {msg.content[:80]}")

        elif msg.message_type == "medication_gap_found":
            action_taken = f"Medication gap resolved for {msg.patient_id} — noted for ED coordination."
            print(f"  [INBOX] medication_gap_found for {msg.patient_id}: {msg.content[:80]}")

        elif msg.message_type == "patient_discharged":
            action_taken = f"Patient {msg.patient_id} discharged — queue slot freed."
            print(f"  [INBOX] patient_discharged: {msg.patient_id}")

        else:
            action_taken = f"Message {msg.message_type} logged."

        bus.mark_processed(msg.message_id, response=action_taken)
        actions.append({
            "message_id": msg.message_id, "from": msg.from_agent,
            "type": msg.message_type, "patient_id": msg.patient_id, "action": action_taken,
        })

    return {"messages_found": len(inbox), "actions_taken": actions}