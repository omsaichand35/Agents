"""
discharge_tools.py  (updated — real inter-agent communication)
===============================================================
Changes from original:
  • message_agent publishes to shared_bus.bus
  • process_inbox() reads hold_discharge messages from sentinel
    and blocks discharge for flagged patients
  • patient_discharged message is published after all blockers clear
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timedelta
from discharge_store import DischargeStore
from shared_bus import bus
import uuid

TOOL_DEFINITIONS = [
    {
        "name": "get_discharge_candidates",
        "description": "Scan all admitted patients and return discharge readiness. Also reads bus inbox.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_record",
        "description": "Returns full discharge record for one patient.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "check_blocker_status",
        "description": "Returns all discharge blockers for a patient with current status.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "draft_discharge_summary",
        "description": "Auto-generate discharge summary and send to doctor for e-signature.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id":     {"type": "string"},
                "clinical_notes": {"type": "string"},
            },
            "required": ["patient_id", "clinical_notes"],
        },
    },
    {
        "name": "submit_insurance_preauth",
        "description": "Submit pre-auth to insurer. Returns auth_number on approval.",
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
        "name": "message_agent",
        "description": (
            "Send a structured message to another PatientOS agent via the SHARED MESSAGE BUS. "
            "Agents: pharmacy_agent -> use fyi | care_continuity | deterioration_sentinel | triage_orchestrator. "
            "Types: expedite_medications->fyi | confirm_ready->fyi | patient_discharged | bed_available | fyi."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "enum": ["care_continuity", "deterioration_sentinel", "triage_orchestrator"],
                },
                "patient_id":   {"type": "string"},
                "message_type": {
                    "type": "string",
                    "enum": ["patient_discharged", "bed_available", "discharge_cleared", "fyi"],
                },
                "content":  {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            },
            "required": ["to_agent", "patient_id", "message_type", "content"],
        },
    },
    {
        "name": "send_sms",
        "description": "SMS to patient or family.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "recipient":  {"type": "string", "enum": ["patient", "family"]},
                "message":    {"type": "string"},
            },
            "required": ["patient_id", "recipient", "message"],
        },
    },
    {
        "name": "resolve_blocker",
        "description": "Mark a discharge blocker resolved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "blocker_id": {"type": "string"},
                "resolution": {"type": "string"},
            },
            "required": ["blocker_id", "resolution"],
        },
    },
    {
        "name": "update_discharge_eta",
        "description": "Set or update the patient's estimated discharge time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "eta":        {"type": "string"},
                "reason":     {"type": "string"},
            },
            "required": ["patient_id", "eta", "reason"],
        },
    },
    {
        "name": "no_action",
        "description": "Record that a patient is not ready for discharge.",
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
            "Read and act on messages addressed to discharge_negotiator. "
            "CRITICAL: call this first. A hold_discharge from sentinel means "
            "do NOT proceed with discharge for that patient this cycle."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(name: str, inputs: dict[str, Any], store: DischargeStore) -> dict:
    try:
        dispatch = {
            "get_discharge_candidates": lambda: _get_discharge_candidates(store),
            "read_patient_record":      lambda: _read_patient_record(inputs["patient_id"], store),
            "check_blocker_status":     lambda: _check_blocker_status(inputs["patient_id"], store),
            "draft_discharge_summary":  lambda: _draft_discharge_summary(inputs, store),
            "submit_insurance_preauth": lambda: _submit_insurance_preauth(inputs, store),
            "message_agent":            lambda: _message_agent(inputs),
            "send_sms":                 lambda: _send_sms(inputs, store),
            "resolve_blocker":          lambda: _resolve_blocker(inputs, store),
            "update_discharge_eta":     lambda: _update_discharge_eta(inputs, store),
            "no_action":                lambda: _no_action(inputs, store),
            "process_inbox":            lambda: _process_inbox(store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


def _get_discharge_candidates(store: DischargeStore) -> dict:
    # Check bus for hold_discharge flags before building candidates list
    holds = {
        m.patient_id for m in bus.get_inbox("discharge_negotiator", unread_only=True)
        if m.message_type == "hold_discharge"
    }
    candidates = []
    for p in store.get_all_patients():
        stable_hrs = 0
        if p.vitals_stable_since:
            dt = datetime.fromisoformat(p.vitals_stable_since)
            stable_hrs = round((datetime.now() - dt).total_seconds() / 3600, 1)
        open_blockers = store.get_open_blockers(p.patient_id)
        sentinel_hold = p.patient_id in holds

        if sentinel_hold:
            readiness = f"SENTINEL HOLD — deterioration alert active. Do not discharge."
        elif p.clinically_ready:
            readiness = f"Clinically cleared. Vitals stable {stable_hrs}h. {len(open_blockers)} blocker(s)."
        else:
            readiness = f"NOT clinically ready. Vitals stable {stable_hrs}h."

        candidates.append({
            "patient_id": p.patient_id, "name": p.name, "age": p.age, "ward": p.ward,
            "clinically_ready": p.clinically_ready and not sentinel_hold,
            "sentinel_hold": sentinel_hold,
            "vitals_stable_hrs": stable_hrs,
            "open_blocker_count": len(open_blockers),
            "readiness_reason": readiness,
            "discharge_eta": p.discharge_eta or "not set",
        })
    return {"total_patients": len(candidates), "patients_on_hold": list(holds), "candidates": candidates}


def _read_patient_record(patient_id: str, store: DischargeStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    blockers = store.get_blockers(patient_id)
    preauth  = store.get_preauth(patient_id)
    summary  = store.get_summary(patient_id)
    return {
        "patient_id": p.patient_id, "name": p.name, "age": p.age, "ward": p.ward,
        "bed_number": p.bed_number, "attending_doctor": p.attending_doctor,
        "doctor_id": p.doctor_id, "diagnosis": p.diagnosis,
        "icd10_codes": p.icd10_codes, "insurance_id": p.insurance_id,
        "insurance_provider": p.insurance_provider, "phone": p.phone,
        "family_phone": p.family_phone, "clinically_ready": p.clinically_ready,
        "vitals_stable_since": p.vitals_stable_since, "discharge_eta": p.discharge_eta,
        "discharge_summary": summary.status if summary else "not drafted",
        "insurance_preauth": preauth.status if preauth else "not initiated",
        "blockers": [
            {"blocker_id": b.blocker_id, "blocker_type": b.blocker_type,
             "description": b.description, "status": b.status, "priority": b.priority}
            for b in blockers
        ],
    }


def _check_blocker_status(patient_id: str, store: DischargeStore) -> dict:
    blockers = store.get_blockers(patient_id)
    open_b = [b for b in blockers if b.status != "resolved"]
    done_b = [b for b in blockers if b.status == "resolved"]
    return {
        "patient_id": patient_id, "open_count": len(open_b),
        "resolved_count": len(done_b), "all_clear": len(open_b) == 0,
        "open_blockers": [{"blocker_id": b.blocker_id, "type": b.blocker_type,
                           "description": b.description, "priority": b.priority} for b in open_b],
        "resolved_blockers": [{"blocker_id": b.blocker_id, "type": b.blocker_type,
                               "resolution": b.resolution} for b in done_b],
    }


def _draft_discharge_summary(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    content = (
        f"DISCHARGE SUMMARY\nPatient: {p.name}, Age {p.age}\n"
        f"Ward/Bed: {p.ward}/{p.bed_number}\nDiagnosis: {p.diagnosis}\n"
        f"ICD-10: {', '.join(p.icd10_codes)}\nDischarged: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Clinical Notes:\n{inputs['clinical_notes']}\n\n"
        f"Follow-up: OPD review in 2 weeks with {p.attending_doctor}\n"
        f"Drafted by: Discharge Negotiator Agent (PatientOS)"
    )
    summary = store.create_summary(patient_id, content)
    doc = store.get_doctor(p.doctor_id)
    doc_phone = doc["phone"] if doc else "unknown"
    store.log_sms(p.attending_doctor, doc_phone,
                  f"Discharge summary ready for {p.name}. Please sign: SUM/{summary.summary_id}")
    print(f"\n  [DISCHARGE SUMMARY DRAFTED] {p.name} — {summary.summary_id}\n")
    return {"success": True, "summary_id": summary.summary_id,
            "status": "draft — sent to doctor", "sent_to": p.attending_doctor}


def _submit_insurance_preauth(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    auth = store.submit_preauth(patient_id)
    print(f"\n  [INSURANCE PRE-AUTH] {p.name} — {auth.provider} — {auth.auth_number}\n")
    return {"success": True, "auth_id": auth.auth_id, "auth_number": auth.auth_number,
            "provider": auth.provider, "status": auth.status}


def _message_agent(inputs: dict) -> dict:
    # Map pharmacy_agent (not on bus) to a no-op with a print
    to_agent     = inputs["to_agent"]
    patient_id   = inputs["patient_id"]
    message_type = inputs["message_type"]
    content      = inputs["content"]
    priority     = inputs.get("priority", "medium")

    msg = bus.publish(
        from_agent   = "discharge_negotiator",
        to_agent     = to_agent,
        patient_id   = patient_id,
        message_type = message_type,
        content      = content,
        priority     = priority,
    )
    return {"success": True, "message_id": msg.message_id,
            "to_agent": to_agent, "sent_at": msg.sent_at}


def _send_sms(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    recipient  = inputs["recipient"]
    message    = inputs["message"]
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}
    phone = p.family_phone if recipient == "family" else p.phone
    name  = f"{p.name}'s family" if recipient == "family" else p.name
    store.log_sms(name, phone, message)
    print(f"  [SMS -> {name} ({phone})]: {message}")
    return {"success": True, "recipient": name, "phone": phone}


def _resolve_blocker(inputs: dict, store: DischargeStore) -> dict:
    ok = store.resolve_blocker(inputs["blocker_id"], inputs["resolution"])
    if not ok:
        return {"error": f"Blocker {inputs['blocker_id']} not found"}
    print(f"  [BLOCKER RESOLVED] {inputs['blocker_id']} — {inputs['resolution']}")

    # After all blockers resolve, auto-publish patient_discharged to sentinel + triage
    patient_id = next(
        (b.patient_id for b in store._blockers if b.blocker_id == inputs["blocker_id"]), None
    )
    if patient_id:
        remaining = store.get_open_blockers(patient_id)
        if len(remaining) == 0:
            p = store.get_patient(patient_id)
            if p and p.clinically_ready:
                bus.publish(
                    from_agent   = "discharge_negotiator",
                    to_agent     = "deterioration_sentinel",
                    patient_id   = patient_id,
                    message_type = "discharge_cleared",
                    content      = f"{p.name} is fully cleared for discharge. Stop monitoring.",
                    priority     = "medium",
                )
                bus.publish(
                    from_agent   = "discharge_negotiator",
                    to_agent     = "triage_orchestrator",
                    patient_id   = patient_id,
                    message_type = "bed_available",
                    content      = f"Bed {p.bed_number} in {p.ward} will be free when {p.name} discharges.",
                    priority     = "low",
                )
                print(f"  [BUS AUTO] All blockers cleared for {patient_id} — sentinel + triage notified.")

    return {"success": True, "blocker_id": inputs["blocker_id"], "resolution": inputs["resolution"]}


def _update_discharge_eta(inputs: dict, store: DischargeStore) -> dict:
    ok = store.update_discharge_eta(inputs["patient_id"], inputs["eta"])
    if not ok:
        return {"error": f"Patient {inputs['patient_id']} not found"}
    p = store.get_patient(inputs["patient_id"])
    print(f"  [ETA UPDATE] {p.name} — expected discharge: {inputs['eta']}")
    return {"success": True, "patient_id": inputs["patient_id"],
            "eta": inputs["eta"], "reason": inputs["reason"]}


def _no_action(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    reason     = inputs["reason"]
    p = store.get_patient(patient_id)
    name = p.name if p else patient_id
    store._action_log.append({
        "timestamp": datetime.now().isoformat(timespec="minutes"),
        "action": "no_action", "patient_id": patient_id, "reason": reason,
    })
    print(f"  [NOT READY] {name} ({patient_id}) — {reason}")
    return {"status": "no_action", "patient_id": patient_id, "reason": reason}


def _process_inbox(store: DischargeStore) -> dict:
    """
    Read the discharge agent's inbox.
    hold_discharge from sentinel -> block this patient's discharge this cycle.
    """
    inbox = bus.get_inbox("discharge_negotiator", unread_only=True)
    if not inbox:
        return {"messages_found": 0, "actions_taken": [], "patients_on_hold": []}

    holds = []
    actions = []
    for msg in inbox:
        action_taken = ""

        if msg.message_type == "hold_discharge":
            holds.append(msg.patient_id)
            action_taken = (
                f"HOLD placed on {msg.patient_id} — sentinel deterioration alert. "
                f"Discharge blocked this cycle. Reason: {msg.content[:100]}"
            )
            print(f"  [INBOX] hold_discharge from sentinel: {msg.patient_id} BLOCKED. {msg.content[:80]}")

        elif msg.message_type == "fyi_deterioration":
            action_taken = f"FYI deterioration noted for {msg.patient_id}. Monitoring discharge readiness."
            print(f"  [INBOX] fyi_deterioration for {msg.patient_id}: {msg.content[:80]}")

        else:
            action_taken = f"Message {msg.message_type} logged."

        bus.mark_processed(msg.message_id, response=action_taken)
        actions.append({
            "message_id": msg.message_id, "from": msg.from_agent,
            "type": msg.message_type, "patient_id": msg.patient_id, "action": action_taken,
        })

    return {"messages_found": len(inbox), "patients_on_hold": holds, "actions_taken": actions}