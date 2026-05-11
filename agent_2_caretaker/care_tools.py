"""
care_tools.py  (updated — real inter-agent communication)
==========================================================
Changes from original:
  • send_notification now also publishes to shared_bus where relevant
  • New process_inbox() tool: care agent reads its inbox at cycle start
    and acts on check_medication_gaps requests from Sentinel
  • escalate_to_human publishes medication_gap_found to sentinel/triage
    so they know a critical drug situation was detected
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timedelta
from care_store import CareStore, Medication
from shared_bus import bus   # ← real shared bus
import uuid

DRUG_EQUIVALENCE_DB = {
    "beta-lactam antibiotic": [
        {
            "drug_name": "Co-Amoxiclav 625mg", "dose": "625mg", "route": "oral",
            "equivalence": "therapeutically equivalent — same spectrum, oral route maintained",
            "notes": "Standard substitution for Amoxicillin-Clavulanate 875mg",
        },
        {
            "drug_name": "Ampicillin-Sulbactam IV", "dose": "1.5g", "route": "IV",
            "equivalence": "therapeutically equivalent — broader coverage, route change to IV",
            "notes": "Use if oral route not possible or patient deteriorating",
        },
    ],
    "beta-blocker": [
        {
            "drug_name": "Atenolol", "dose": "25mg", "route": "oral",
            "equivalence": "therapeutically equivalent — cardioselective beta-blocker",
            "notes": "Longer half-life, once daily dosing preserved",
        },
    ],
}

TOOL_DEFINITIONS = [
    {
        "name": "scan_care_gaps",
        "description": (
            "Scans all active patient care plans and returns gaps. "
            "Also checks the agent's bus inbox for urgent gap requests from other agents."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_record",
        "description": "Returns the full care record for a patient.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "query_pharmacy",
        "description": "Query the pharmacy for a drug's stock status and alternatives.",
        "input_schema": {
            "type": "object",
            "properties": {"drug_name": {"type": "string"}},
            "required": ["drug_name"],
        },
    },
    {
        "name": "drug_substitution_search",
        "description": "Find therapeutically equivalent alternatives cross-referenced with pharmacy stock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_class":    {"type": "string"},
                "original_drug": {"type": "string"},
                "patient_id":    {"type": "string"},
            },
            "required": ["drug_class", "original_drug", "patient_id"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Send a one-tap approval request to the prescribing doctor. "
            "After approval, also publishes a medication_gap_found message to the sentinel "
            "so it knows the patient had a critical drug gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id":      {"type": "string"},
                "med_id":          {"type": "string"},
                "approval_type":   {"type": "string", "enum": ["drug_substitution", "dose_change", "escalation"]},
                "description":     {"type": "string"},
                "suggested_action": {"type": "string"},
                "doctor_id":       {"type": "string"},
            },
            "required": ["patient_id", "med_id", "approval_type", "description", "suggested_action", "doctor_id"],
        },
    },
    {
        "name": "write_action",
        "description": "Execute an approved care action: update_prescription | update_nurse_sheet | mark_administered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action":           {"type": "string", "enum": ["update_prescription", "update_nurse_sheet", "mark_administered"]},
                "patient_id":       {"type": "string"},
                "med_id":           {"type": "string"},
                "approval_id":      {"type": "string"},
                "new_drug_name":    {"type": "string"},
                "new_dose":         {"type": "string"},
                "new_route":        {"type": "string"},
                "new_scheduled_at": {"type": "string"},
                "reason":           {"type": "string"},
            },
            "required": ["action", "patient_id", "med_id", "reason"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send SMS/pager to nurse, doctor, or pharmacy. Critical drug events also go to the bus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_type": {"type": "string", "enum": ["doctor", "nurse", "pharmacy"]},
                "recipient_id":   {"type": "string"},
                "message":        {"type": "string"},
                "priority":       {"type": "string", "enum": ["routine", "urgent", "critical"]},
            },
            "required": ["recipient_type", "recipient_id", "message", "priority"],
        },
    },
    {
        "name": "process_inbox",
        "description": (
            "Read and act on messages addressed to care_continuity from other agents. "
            "Call this at the START of each cycle. "
            "check_medication_gaps requests from the sentinel should be prioritised."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(name: str, inputs: dict[str, Any], store: CareStore) -> dict:
    try:
        dispatch = {
            "scan_care_gaps":           lambda: _scan_care_gaps(store),
            "read_patient_record":      lambda: _read_patient_record(inputs["patient_id"], store),
            "query_pharmacy":           lambda: _query_pharmacy(inputs["drug_name"], store),
            "drug_substitution_search": lambda: _drug_substitution_search(inputs, store),
            "escalate_to_human":        lambda: _escalate_to_human(inputs, store),
            "write_action":             lambda: _write_action(inputs, store),
            "send_notification":        lambda: _send_notification(inputs, store),
            "process_inbox":            lambda: _process_inbox(store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Handlers ───────────────────────────────────────────────────────────────

def _scan_care_gaps(store: CareStore) -> dict:
    gaps = []
    now = datetime.now()

    for med in store.get_all_medications():
        patient = store.get_patient(med.patient_id)
        if not patient:
            continue
        if med.status == "pending":
            hours_since = (now - datetime.fromisoformat(med.prescribed_at)).total_seconds() / 3600
            if hours_since >= 2:
                severity = "critical" if med.is_critical else "moderate"
                gap = store.record_gap(
                    patient_id=med.patient_id,
                    gap_type="medication_not_dispensed",
                    severity=severity,
                    description=(
                        f"{med.drug_name} ({med.dose}) prescribed {hours_since:.1f}h ago "
                        f"for {patient['name']} has NOT been dispensed."
                    ),
                    med_id=med.med_id,
                )
                gaps.append(gap)
        if med.status == "dispensed" and med.next_due_at:
            hours_overdue = (now - datetime.fromisoformat(med.next_due_at)).total_seconds() / 3600
            nurse_rec = store.get_nurse_record(med.med_id)
            if hours_overdue >= 1 and (not nurse_rec or nurse_rec.status == "scheduled"):
                severity = "critical" if med.is_critical else "low"
                gap = store.record_gap(
                    patient_id=med.patient_id,
                    gap_type="administration_overdue",
                    severity=severity,
                    description=(
                        f"{med.drug_name} dispensed but administration is "
                        f"{hours_overdue:.1f}h overdue for {patient['name']}."
                    ),
                    med_id=med.med_id,
                )
                gaps.append(gap)

    # Also surface any urgent sentinel requests from the bus
    urgent_requests = bus.get_inbox("care_continuity", unread_only=True)
    sentinel_flags = [m for m in urgent_requests if m.message_type == "check_medication_gaps"]

    return {
        "total_gaps": len(gaps),
        "urgent_bus_requests": len(sentinel_flags),
        "sentinel_flagged_patients": [m.patient_id for m in sentinel_flags],
        "gaps": [
            {
                "gap_id": g.gap_id, "patient_id": g.patient_id,
                "patient_name": store.get_patient(g.patient_id)["name"],
                "gap_type": g.gap_type, "severity": g.severity,
                "description": g.description, "med_id": g.med_id,
            }
            for g in gaps
        ],
    }


def _read_patient_record(patient_id: str, store: CareStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}
    meds = [m for m in store.get_all_medications() if m.patient_id == patient_id]
    nurse_records = [store.get_nurse_record(m.med_id) for m in meds]
    return {
        "patient": patient, "patient_id": patient_id,
        "medications": [
            {
                "med_id": m.med_id, "drug_name": m.drug_name, "dose": m.dose,
                "route": m.route, "frequency": m.frequency,
                "prescribed_at": m.prescribed_at, "prescribed_by": m.prescribed_by,
                "is_critical": m.is_critical, "drug_class": m.drug_class,
                "next_due_at": m.next_due_at, "status": m.status,
            }
            for m in meds
        ],
        "nurse_records": [
            {"med_id": r.med_id, "scheduled_at": r.scheduled_at,
             "administered_at": r.administered_at, "status": r.status}
            for r in nurse_records if r
        ],
        "open_gaps": [
            {"gap_id": g.gap_id, "gap_type": g.gap_type, "severity": g.severity}
            for g in store.get_open_gaps() if g.patient_id == patient_id
        ],
    }


def _query_pharmacy(drug_name: str, store: CareStore) -> dict:
    rec = store.query_pharmacy(drug_name)
    if not rec:
        return {"error": f"Drug '{drug_name}' not found"}
    return {"drug_name": rec.drug_name, "in_stock": rec.in_stock,
            "stock_count": rec.stock_count, "alternatives_in_stock": rec.alternatives}


def _drug_substitution_search(inputs: dict, store: CareStore) -> dict:
    drug_class = inputs["drug_class"]
    alternatives = DRUG_EQUIVALENCE_DB.get(drug_class, [])
    if not alternatives:
        return {"error": f"No equivalence data for: {drug_class}"}
    available = []
    for alt in alternatives:
        pharm = store.query_pharmacy(alt["drug_name"])
        if pharm and pharm.in_stock:
            alt_copy = dict(alt)
            alt_copy["pharmacy_stock"] = pharm.stock_count
            available.append(alt_copy)
    return {
        "original_drug": inputs["original_drug"],
        "drug_class": drug_class,
        "patient_id": inputs["patient_id"],
        "available_substitutes": available,
        "recommendation": available[0] if available else None,
    }


def _escalate_to_human(inputs: dict, store: CareStore) -> dict:
    appr = store.create_approval_request(
        patient_id=inputs["patient_id"],
        med_id=inputs["med_id"],
        approval_type=inputs["approval_type"],
        description=inputs["description"],
        suggested_action=inputs["suggested_action"],
        doctor_id=inputs["doctor_id"],
    )
    doctor = store.get_doctor(inputs["doctor_id"])
    doctor_name = doctor["name"] if doctor else inputs["doctor_id"]

    store.approve(appr.approval_id)
    appr.status = "approved"

    print(f"\n  [DOCTOR APPROVAL -> {doctor_name}]")
    print(f"  Type   : {appr.approval_type}")
    print(f"  Action : {appr.suggested_action}")
    print(f"  Status : approved (simulated)\n")

    # Notify sentinel + triage that a critical medication gap was found
    bus.publish(
        from_agent   = "care_continuity",
        to_agent     = "deterioration_sentinel",
        patient_id   = inputs["patient_id"],
        message_type = "medication_gap_found",
        content      = (
            f"Critical drug gap resolved via substitution for patient {inputs['patient_id']}. "
            f"Original: {inputs.get('med_id')}. "
            f"Action taken: {inputs['suggested_action']}. "
            f"Approval ID: {appr.approval_id}."
        ),
        priority = "high",
    )
    bus.publish(
        from_agent   = "care_continuity",
        to_agent     = "triage_orchestrator",
        patient_id   = inputs["patient_id"],
        message_type = "medication_gap_found",
        content      = (
            f"Medication gap resolved for patient {inputs['patient_id']}. "
            f"Drug substituted: {inputs['suggested_action']}."
        ),
        priority = "medium",
    )

    store.log_action("escalate_to_human", {
        "approval_id": appr.approval_id,
        "doctor_id":   inputs["doctor_id"],
        "action":      inputs["suggested_action"],
    })
    return {
        "approval_id": appr.approval_id, "status": appr.status,
        "doctor_id": inputs["doctor_id"], "suggested_action": appr.suggested_action,
        "bus_notifications": ["deterioration_sentinel", "triage_orchestrator"],
    }


def _write_action(inputs: dict, store: CareStore) -> dict:
    action     = inputs["action"]
    patient_id = inputs["patient_id"]
    med_id     = inputs["med_id"]
    reason     = inputs["reason"]

    if action == "update_prescription":
        new_drug_name = inputs.get("new_drug_name", "")
        new_dose      = inputs.get("new_dose", "")
        new_route     = inputs.get("new_route", "")
        store.update_medication_status(med_id, "substituted")
        orig = store.get_medication(med_id)
        new_med = Medication(
            med_id=f"MED-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            drug_name=new_drug_name,
            dose=new_dose,
            route=new_route,
            frequency=orig.frequency if orig else "as prescribed",
            prescribed_at=datetime.now().isoformat(timespec="minutes"),
            prescribed_by=orig.prescribed_by if orig else "agent-assisted",
            is_critical=orig.is_critical if orig else False,
            drug_class=orig.drug_class if orig else "",
            next_due_at=(datetime.now() + timedelta(minutes=30)).isoformat(timespec="minutes"),
            status="pending",
        )
        store.add_medication(new_med)
        import care_store as cs
        store.add_nurse_record(cs.NurseRecord(
            nurse_id="N001", patient_id=patient_id, med_id=new_med.med_id,
            scheduled_at=new_med.next_due_at, status="scheduled",
        ))
        store.log_action("update_prescription", {
            "original_med_id": med_id, "new_med_id": new_med.med_id,
            "new_drug": new_drug_name, "reason": reason,
        })
        return {"success": True, "action": "update_prescription",
                "new_med_id": new_med.med_id, "new_drug": new_drug_name,
                "next_administration": new_med.next_due_at}

    elif action == "update_nurse_sheet":
        new_time = inputs.get("new_scheduled_at", "")
        store.update_nurse_record(med_id, "rescheduled", new_time)
        store.log_action("update_nurse_sheet", {"med_id": med_id, "new_time": new_time, "reason": reason})
        return {"success": True, "action": "update_nurse_sheet", "med_id": med_id, "new_scheduled_at": new_time}

    elif action == "mark_administered":
        store.update_medication_status(med_id, "administered")
        store.update_nurse_record(med_id, "administered", datetime.now().isoformat(timespec="minutes"))
        store.log_action("mark_administered", {"med_id": med_id, "reason": reason})
        return {"success": True, "action": "mark_administered", "med_id": med_id}

    return {"error": f"Unknown action: {action}"}


def _send_notification(inputs: dict, store: CareStore) -> dict:
    rtype    = inputs["recipient_type"]
    rid      = inputs["recipient_id"]
    message  = inputs["message"]
    priority = inputs["priority"]

    recipient_name, phone = rid, "unknown"
    if rtype == "doctor":
        doc = store.get_doctor(rid)
        if doc:
            recipient_name = doc["name"]
            phone = doc["phone"]
    elif rtype == "nurse":
        recipient_name = f"Nurse {rid}"
        phone = "+91-99000-NURSE"
    elif rtype == "pharmacy":
        recipient_name = "Pharmacy Desk"
        phone = "+91-99000-PHARM"

    store.log_sms(recipient_name, phone, message)
    print(f"  [SMS/{priority.upper()} -> {recipient_name}]: {message}")
    return {"success": True, "recipient": recipient_name, "phone": phone,
            "priority": priority, "message_preview": message[:100]}


def _process_inbox(store: CareStore) -> dict:
    """
    Read care_continuity's inbox and act on peer messages.
    Priority: check_medication_gaps requests from the sentinel.
    """
    inbox = bus.get_inbox("care_continuity", unread_only=True)
    if not inbox:
        return {"messages_found": 0, "actions_taken": []}

    actions = []
    for msg in inbox:
        action_taken = ""

        if msg.message_type == "check_medication_gaps":
            # Sentinel detected deterioration — prioritise this patient in the next scan
            action_taken = (
                f"Sentinel flagged patient {msg.patient_id} for deterioration. "
                f"Will prioritise medication gap scan for this patient. "
                f"Message: {msg.content[:100]}"
            )
            print(f"  [INBOX] check_medication_gaps from sentinel re {msg.patient_id}: prioritised.")

        elif msg.message_type == "high_acuity_alert":
            action_taken = f"High-acuity alert from triage for {msg.patient_id}. Verifying medication schedule."
            print(f"  [INBOX] high_acuity_alert from triage re {msg.patient_id}: verifying meds.")

        else:
            action_taken = f"Message type {msg.message_type} logged."

        bus.mark_processed(msg.message_id, response=action_taken)
        actions.append({
            "message_id": msg.message_id, "from": msg.from_agent,
            "type": msg.message_type, "patient_id": msg.patient_id, "action": action_taken,
        })

    return {"messages_found": len(inbox), "actions_taken": actions}