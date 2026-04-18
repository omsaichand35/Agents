"""
care_tools.py
=============
Tools available to the Care Continuity Agent.

  scan_care_gaps            — check all active care plans for gaps
  read_patient_record       — full clinical + medication record for one patient
  query_pharmacy            — check drug stock and get alternatives
  drug_substitution_search  — find therapeutically equivalent drug for a given class
  escalate_to_human         — send doctor a one-tap approval request
  write_action              — update prescription / nurse sheet / schedule
  send_notification         — SMS/pager to nurse or doctor
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timedelta
from care_store import CareStore, Medication
import uuid

# ── Drug substitution knowledge base (simplified) ──────────────────────────
# In production: query a real drug DB (e.g. RxNorm, Lexicomp, Micromedex API)
DRUG_EQUIVALENCE_DB = {
    "beta-lactam antibiotic": [
        {
            "drug_name": "Co-Amoxiclav 625mg",
            "dose": "625mg",
            "route": "oral",
            "equivalence": "therapeutically equivalent — same spectrum, oral route maintained",
            "notes": "Standard substitution for Amoxicillin-Clavulanate 875mg when unavailable",
        },
        {
            "drug_name": "Ampicillin-Sulbactam IV",
            "dose": "1.5g",
            "route": "IV",
            "equivalence": "therapeutically equivalent — broader coverage, route change to IV",
            "notes": "Use if oral route not possible or patient deteriorating",
        },
    ],
    "beta-blocker": [
        {
            "drug_name": "Atenolol",
            "dose": "25mg",
            "route": "oral",
            "equivalence": "therapeutically equivalent — cardioselective beta-blocker",
            "notes": "Longer half-life, once daily dosing preserved",
        },
        {
            "drug_name": "Bisoprolol",
            "dose": "2.5mg",
            "route": "oral",
            "equivalence": "therapeutically equivalent — preferred in heart failure",
            "notes": "May be superior if patient has concurrent HF",
        },
    ],
}


# ── Tool schemas ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "scan_care_gaps",
        "description": (
            "Scans all active patient care plans and returns a list of detected gaps. "
            "A gap is any prescribed medication that has not been dispensed within 2 hours "
            "of prescription, any dispensed medication not confirmed administered within "
            "1 hour of scheduled time, or any overdue vitals/procedure. "
            "Returns gap_id, patient_id, severity, and description for each gap found."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_record",
        "description": (
            "Returns the full care record for a patient: demographics, diagnosis, "
            "all prescribed medications with current status, nurse administration log, "
            "and any open care gaps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient ID e.g. P001"}
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "query_pharmacy",
        "description": (
            "Query the pharmacy for a specific drug's stock status. "
            "Returns in_stock (bool), stock_count, and a list of known alternatives "
            "stocked in the pharmacy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string", "description": "Exact drug name to query"}
            },
            "required": ["drug_name"],
        },
    },
    {
        "name": "drug_substitution_search",
        "description": (
            "Search the drug equivalence database for therapeutically equivalent "
            "alternatives for a given drug class. Returns a ranked list of substitutes "
            "with dose, route, equivalence rationale, and clinical notes. "
            "Cross-references with pharmacy stock to return only available options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_class": {
                    "type": "string",
                    "description": "Drug class e.g. 'beta-lactam antibiotic', 'beta-blocker'",
                },
                "original_drug": {"type": "string", "description": "Name of the drug being substituted"},
                "patient_id": {"type": "string", "description": "Patient ID for context"},
            },
            "required": ["drug_class", "original_drug", "patient_id"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Send a one-tap approval request to the prescribing doctor. "
            "Use this when a drug substitution or other clinical change requires "
            "physician sign-off before the agent can execute it. "
            "Returns an approval_id that can be polled or acted on once approved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "med_id": {"type": "string", "description": "The medication with the gap"},
                "approval_type": {
                    "type": "string",
                    "enum": ["drug_substitution", "dose_change", "escalation"],
                },
                "description": {
                    "type": "string",
                    "description": "Plain-English explanation of the gap and why action is needed",
                },
                "suggested_action": {
                    "type": "string",
                    "description": "The specific action awaiting approval (e.g. 'Substitute with Co-Amoxiclav 625mg oral')",
                },
                "doctor_id": {"type": "string"},
            },
            "required": ["patient_id", "med_id", "approval_type", "description", "suggested_action", "doctor_id"],
        },
    },
    {
        "name": "write_action",
        "description": (
            "Execute an approved care action. Actions: "
            "'update_prescription' — mark original med as substituted and create new med order; "
            "'update_nurse_sheet' — reschedule or update administration record; "
            "'mark_administered' — confirm a nurse has administered a medication."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["update_prescription", "update_nurse_sheet", "mark_administered"],
                },
                "patient_id": {"type": "string"},
                "med_id": {"type": "string", "description": "Original medication ID"},
                "approval_id": {
                    "type": "string",
                    "description": "approval_id from escalate_to_human (required for prescription changes)",
                },
                "new_drug_name": {"type": "string", "description": "For update_prescription"},
                "new_dose": {"type": "string"},
                "new_route": {"type": "string"},
                "new_scheduled_at": {
                    "type": "string",
                    "description": "For update_nurse_sheet: ISO timestamp for rescheduled administration",
                },
                "reason": {"type": "string"},
            },
            "required": ["action", "patient_id", "med_id", "reason"],
        },
    },
    {
        "name": "send_notification",
        "description": (
            "Send an SMS or pager alert to a nurse or doctor. "
            "Use after write_action to inform relevant staff of changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_type": {"type": "string", "enum": ["doctor", "nurse", "pharmacy"]},
                "recipient_id": {"type": "string"},
                "message": {"type": "string"},
                "priority": {"type": "string", "enum": ["routine", "urgent", "critical"]},
            },
            "required": ["recipient_type", "recipient_id", "message", "priority"],
        },
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────

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
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Handlers ──────────────────────────────────────────────────────────────

def _scan_care_gaps(store: CareStore) -> dict:
    gaps = []
    now = datetime.now()

    for med in store.get_all_medications():
        patient = store.get_patient(med.patient_id)
        if not patient:
            continue

        # Gap 1: prescribed but never dispensed past 2 hours
        if med.status == "pending":
            prescribed_dt = datetime.fromisoformat(med.prescribed_at)
            hours_since = (now - prescribed_dt).total_seconds() / 3600
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

        # Gap 2: dispensed but administration overdue > 1 hour
        if med.status == "dispensed" and med.next_due_at:
            due_dt = datetime.fromisoformat(med.next_due_at)
            hours_overdue = (now - due_dt).total_seconds() / 3600
            nurse_rec = store.get_nurse_record(med.med_id)
            if hours_overdue >= 1 and (not nurse_rec or nurse_rec.status == "scheduled"):
                severity = "critical" if med.is_critical else "low"
                gap = store.record_gap(
                    patient_id=med.patient_id,
                    gap_type="administration_overdue",
                    severity=severity,
                    description=(
                        f"{med.drug_name} dispensed but administration by nurse "
                        f"is {hours_overdue:.1f}h overdue for {patient['name']}."
                    ),
                    med_id=med.med_id,
                )
                gaps.append(gap)

    return {
        "total_gaps": len(gaps),
        "gaps": [
            {
                "gap_id": g.gap_id,
                "patient_id": g.patient_id,
                "patient_name": store.get_patient(g.patient_id)["name"],
                "gap_type": g.gap_type,
                "severity": g.severity,
                "description": g.description,
                "med_id": g.med_id,
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
        "patient": patient,
        "patient_id": patient_id,
        "medications": [
            {
                "med_id": m.med_id,
                "drug_name": m.drug_name,
                "dose": m.dose,
                "route": m.route,
                "frequency": m.frequency,
                "prescribed_at": m.prescribed_at,
                "prescribed_by": m.prescribed_by,
                "is_critical": m.is_critical,
                "drug_class": m.drug_class,
                "next_due_at": m.next_due_at,
                "status": m.status,
            }
            for m in meds
        ],
        "nurse_records": [
            {
                "med_id": r.med_id,
                "scheduled_at": r.scheduled_at,
                "administered_at": r.administered_at,
                "status": r.status,
            }
            for r in nurse_records if r
        ],
        "open_gaps": [
            {"gap_id": g.gap_id, "gap_type": g.gap_type, "severity": g.severity}
            for g in store.get_open_gaps()
            if g.patient_id == patient_id
        ],
    }


def _query_pharmacy(drug_name: str, store: CareStore) -> dict:
    rec = store.query_pharmacy(drug_name)
    if not rec:
        return {"error": f"Drug '{drug_name}' not in pharmacy database"}
    return {
        "drug_name": rec.drug_name,
        "in_stock": rec.in_stock,
        "stock_count": rec.stock_count,
        "alternatives_in_stock": rec.alternatives,
    }


def _drug_substitution_search(inputs: dict, store: CareStore) -> dict:
    drug_class = inputs["drug_class"]
    original   = inputs["original_drug"]
    patient_id = inputs["patient_id"]

    alternatives = DRUG_EQUIVALENCE_DB.get(drug_class, [])
    if not alternatives:
        return {"error": f"No equivalence data for drug class: {drug_class}"}

    # Cross-reference with pharmacy stock
    available = []
    for alt in alternatives:
        pharm = store.query_pharmacy(alt["drug_name"])
        if pharm and pharm.in_stock:
            alt_copy = dict(alt)
            alt_copy["pharmacy_stock"] = pharm.stock_count
            available.append(alt_copy)

    return {
        "original_drug": original,
        "drug_class": drug_class,
        "patient_id": patient_id,
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

    # Simulate doctor auto-approving in demo (in prod: real pager/app push)
    store.approve(appr.approval_id)
    appr.status = "approved"

    print(f"\n  [DOCTOR APPROVAL REQUEST → {doctor_name}]")
    print(f"  Type       : {appr.approval_type}")
    print(f"  Description: {appr.description}")
    print(f"  Action     : {appr.suggested_action}")
    print(f"  Approval ID: {appr.approval_id}")
    print(f"  ✓ Doctor approved via one-tap (simulated)\n")

    store.log_action("escalate_to_human", {
        "approval_id": appr.approval_id,
        "doctor_id": inputs["doctor_id"],
        "action": inputs["suggested_action"],
    })

    return {
        "approval_id": appr.approval_id,
        "status": appr.status,
        "doctor_id": inputs["doctor_id"],
        "suggested_action": appr.suggested_action,
        "message": "Approval request sent. Doctor approved.",
    }


def _write_action(inputs: dict, store: CareStore) -> dict:
    action     = inputs["action"]
    patient_id = inputs["patient_id"]
    med_id     = inputs["med_id"]
    reason     = inputs["reason"]

    if action == "update_prescription":
        approval_id   = inputs.get("approval_id", "")
        new_drug_name = inputs.get("new_drug_name", "")
        new_dose      = inputs.get("new_dose", "")
        new_route     = inputs.get("new_route", "")

        # Mark original as substituted
        store.update_medication_status(med_id, "substituted")

        # Create new medication order
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

        # Schedule nurse record for new med
        store.add_nurse_record(
            __import__("care_store").NurseRecord(
                nurse_id="N001",
                patient_id=patient_id,
                med_id=new_med.med_id,
                scheduled_at=new_med.next_due_at,
                status="scheduled",
            )
        )

        store.log_action("update_prescription", {
            "original_med_id": med_id,
            "new_med_id": new_med.med_id,
            "new_drug": new_drug_name,
            "approval_id": approval_id,
            "reason": reason,
        })

        return {
            "success": True,
            "action": "update_prescription",
            "original_med": med_id,
            "new_med_id": new_med.med_id,
            "new_drug": new_drug_name,
            "new_dose": new_dose,
            "new_route": new_route,
            "next_administration": new_med.next_due_at,
        }

    elif action == "update_nurse_sheet":
        new_time = inputs.get("new_scheduled_at", "")
        store.update_nurse_record(med_id, "rescheduled", new_time)
        store.log_action("update_nurse_sheet", {"med_id": med_id, "new_time": new_time, "reason": reason})
        return {"success": True, "action": "update_nurse_sheet", "med_id": med_id, "new_scheduled_at": new_time}

    elif action == "mark_administered":
        store.update_medication_status(med_id, "administered")
        store.update_nurse_record(med_id, "administered",
                                  datetime.now().isoformat(timespec="minutes"))
        store.log_action("mark_administered", {"med_id": med_id, "reason": reason})
        return {"success": True, "action": "mark_administered", "med_id": med_id}

    return {"error": f"Unknown action: {action}"}


def _send_notification(inputs: dict, store: CareStore) -> dict:
    rtype      = inputs["recipient_type"]
    rid        = inputs["recipient_id"]
    message    = inputs["message"]
    priority   = inputs["priority"]

    recipient_name = rid
    phone = "unknown"

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
    print(f"  [SMS/{priority.upper()} → {recipient_name} ({phone})]: {message}")

    return {
        "success": True,
        "recipient": recipient_name,
        "phone": phone,
        "priority": priority,
        "message_preview": message[:100],
    }