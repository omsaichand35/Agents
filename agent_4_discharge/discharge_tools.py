"""
discharge_tools.py
==================
Tools available to the Discharge Negotiator Agent.

  get_discharge_candidates    — scan all admitted patients, return those ready (or not)
  read_patient_record         — full clinical + blocker record for one patient
  check_blocker_status        — get all blockers and their current state
  draft_discharge_summary     — auto-generate discharge summary (sent to doctor)
  submit_insurance_preauth    — submit pre-auth request to insurer with ICD-10 codes
  message_agent               — coordinate with pharmacy / sentinel / triage agents
  send_sms                    — notify patient or family member
  resolve_blocker             — mark a blocker resolved after action taken
  update_discharge_eta        — set / update patient's estimated discharge time
  no_action                   — record that a patient is not ready yet
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timedelta
from discharge_store import DischargeStore

# ── Tool definitions ──────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_discharge_candidates",
        "description": (
            "Scan all admitted patients and return their discharge readiness. "
            "For each patient returns: patient_id, name, clinically_ready (bool), "
            "vitals_stable_since, open_blocker_count, and a readiness_reason. "
            "Call this at the start of every cycle to build your worklist."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_record",
        "description": (
            "Returns the full discharge record for one patient: "
            "demographics, diagnosis, ICD-10 codes, insurance details, "
            "all discharge blockers with their status, and current ETA."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "e.g. DIS-001"}
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "check_blocker_status",
        "description": (
            "Returns a detailed list of all discharge blockers for a patient "
            "with their current status (pending / in_progress / resolved). "
            "Use this to see exactly what is still blocking discharge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"}
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "draft_discharge_summary",
        "description": (
            "Auto-generate a discharge summary for a patient using their clinical record. "
            "The summary is immediately sent to the attending doctor for review and e-signature. "
            "Returns summary_id and confirms it has been sent to the doctor. "
            "After calling this, resolve the 'summary' blocker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "clinical_notes": {
                    "type": "string",
                    "description": "Key clinical details to include: diagnosis, treatment course, "
                                   "outcome, follow-up instructions, discharge medications.",
                },
            },
            "required": ["patient_id", "clinical_notes"],
        },
    },
    {
        "name": "submit_insurance_preauth",
        "description": (
            "Submit a pre-authorisation request to the patient's insurer. "
            "Pulls ICD-10 codes and insurance ID from the patient record automatically. "
            "Returns auth_number on approval. After calling this, resolve the 'insurance' blocker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "Clinical justification for the pre-auth request.",
                },
            },
            "required": ["patient_id", "reason"],
        },
    },
    {
        "name": "message_agent",
        "description": (
            "Send a structured message to another PatientOS agent. "
            "Use this to coordinate blockers that other agents own:\n"
            "  → pharmacy_agent: expedite take-home medications\n"
            "  → care_continuity: confirm medications administered and patient ready\n"
            "  → deterioration_sentinel: notify them patient is discharged (stop monitoring)\n"
            "  → triage_orchestrator: free up a bed\n"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "enum": ["pharmacy_agent", "care_continuity", "deterioration_sentinel", "triage_orchestrator"],
                },
                "patient_id": {"type": "string"},
                "message_type": {
                    "type": "string",
                    "enum": ["expedite_medications", "confirm_ready", "patient_discharged", "bed_available", "fyi"],
                },
                "content": {"type": "string"},
            },
            "required": ["to_agent", "patient_id", "message_type", "content"],
        },
    },
    {
        "name": "send_sms",
        "description": (
            "Send an SMS to the patient or their family. "
            "Use for: ETA updates, transport coordination, discharge confirmation, "
            "post-discharge follow-up instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "recipient": {
                    "type": "string",
                    "enum": ["patient", "family"],
                    "description": "Who to send the SMS to.",
                },
                "message": {"type": "string"},
            },
            "required": ["patient_id", "recipient", "message"],
        },
    },
    {
        "name": "resolve_blocker",
        "description": (
            "Mark a specific discharge blocker as resolved. "
            "Always call this after successfully completing the action that addresses the blocker. "
            "Provide a concise resolution string explaining what was done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "blocker_id": {"type": "string", "description": "e.g. BLK-001"},
                "resolution": {
                    "type": "string",
                    "description": "What action resolved this blocker.",
                },
            },
            "required": ["blocker_id", "resolution"],
        },
    },
    {
        "name": "update_discharge_eta",
        "description": (
            "Set or update the patient's estimated discharge time. "
            "Call this whenever the ETA changes — after resolving blockers or "
            "discovering a new delay. Always SMS the patient after updating ETA."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "eta": {
                    "type": "string",
                    "description": "Human-readable ETA e.g. '3:30 PM today'",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this ETA was set or updated.",
                },
            },
            "required": ["patient_id", "eta", "reason"],
        },
    },
    {
        "name": "no_action",
        "description": (
            "Record that a patient is not ready for discharge in this cycle. "
            "Always call this for patients who are not clinically cleared "
            "so the audit log is complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "reason":     {"type": "string"},
            },
            "required": ["patient_id", "reason"],
        },
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict[str, Any], store: DischargeStore) -> dict:
    try:
        dispatch = {
            "get_discharge_candidates": lambda: _get_discharge_candidates(store),
            "read_patient_record":      lambda: _read_patient_record(inputs["patient_id"], store),
            "check_blocker_status":     lambda: _check_blocker_status(inputs["patient_id"], store),
            "draft_discharge_summary":  lambda: _draft_discharge_summary(inputs, store),
            "submit_insurance_preauth": lambda: _submit_insurance_preauth(inputs, store),
            "message_agent":            lambda: _message_agent(inputs, store),
            "send_sms":                 lambda: _send_sms(inputs, store),
            "resolve_blocker":          lambda: _resolve_blocker(inputs, store),
            "update_discharge_eta":     lambda: _update_discharge_eta(inputs, store),
            "no_action":                lambda: _no_action(inputs, store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Handlers ──────────────────────────────────────────────────────────────

def _get_discharge_candidates(store: DischargeStore) -> dict:
    candidates = []
    for p in store.get_all_patients():
        # Compute vitals stability in hours
        stable_hrs = 0
        if p.vitals_stable_since:
            dt = datetime.fromisoformat(p.vitals_stable_since)
            stable_hrs = round((datetime.now() - dt).total_seconds() / 3600, 1)

        open_blockers = store.get_open_blockers(p.patient_id)

        if p.clinically_ready:
            readiness = f"Clinically cleared. Vitals stable {stable_hrs}h. {len(open_blockers)} blocker(s) remaining."
        else:
            readiness = f"NOT clinically ready. Vitals stable only {stable_hrs}h — minimum 24h required."

        candidates.append({
            "patient_id":        p.patient_id,
            "name":              p.name,
            "age":               p.age,
            "ward":              p.ward,
            "clinically_ready":  p.clinically_ready,
            "vitals_stable_hrs": stable_hrs,
            "open_blocker_count": len(open_blockers),
            "readiness_reason":  readiness,
            "discharge_eta":     p.discharge_eta or "not set",
        })

    return {"total_patients": len(candidates), "candidates": candidates}


def _read_patient_record(patient_id: str, store: DischargeStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    blockers = store.get_blockers(patient_id)
    preauth  = store.get_preauth(patient_id)
    summary  = store.get_summary(patient_id)

    return {
        "patient_id":          p.patient_id,
        "name":                p.name,
        "age":                 p.age,
        "ward":                p.ward,
        "bed_number":          p.bed_number,
        "attending_doctor":    p.attending_doctor,
        "doctor_id":           p.doctor_id,
        "diagnosis":           p.diagnosis,
        "icd10_codes":         p.icd10_codes,
        "insurance_id":        p.insurance_id,
        "insurance_provider":  p.insurance_provider,
        "phone":               p.phone,
        "family_phone":        p.family_phone,
        "clinically_ready":    p.clinically_ready,
        "vitals_stable_since": p.vitals_stable_since,
        "discharge_eta":       p.discharge_eta,
        "discharge_summary":   summary.status if summary else "not drafted",
        "insurance_preauth":   preauth.status if preauth else "not initiated",
        "blockers": [
            {
                "blocker_id":   b.blocker_id,
                "blocker_type": b.blocker_type,
                "description":  b.description,
                "status":       b.status,
                "priority":     b.priority,
            }
            for b in blockers
        ],
    }


def _check_blocker_status(patient_id: str, store: DischargeStore) -> dict:
    blockers = store.get_blockers(patient_id)
    open_b   = [b for b in blockers if b.status != "resolved"]
    done_b   = [b for b in blockers if b.status == "resolved"]

    return {
        "patient_id":       patient_id,
        "open_count":       len(open_b),
        "resolved_count":   len(done_b),
        "all_clear":        len(open_b) == 0,
        "open_blockers": [
            {"blocker_id": b.blocker_id, "type": b.blocker_type,
             "description": b.description, "priority": b.priority}
            for b in open_b
        ],
        "resolved_blockers": [
            {"blocker_id": b.blocker_id, "type": b.blocker_type,
             "resolution": b.resolution}
            for b in done_b
        ],
    }


def _draft_discharge_summary(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    notes      = inputs["clinical_notes"]
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    content = (
        f"DISCHARGE SUMMARY\n"
        f"Patient     : {p.name}, Age {p.age}\n"
        f"Ward / Bed  : {p.ward} / {p.bed_number}\n"
        f"Diagnosis   : {p.diagnosis}\n"
        f"ICD-10      : {', '.join(p.icd10_codes)}\n"
        f"Admitted    : {p.admitted_at}\n"
        f"Discharged  : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Clinical Notes:\n{notes}\n\n"
        f"Follow-up   : OPD review in 2 weeks with {p.attending_doctor}\n"
        f"Emergency   : Return to ED if fever > 38.5°C, wound discharge, or severe pain.\n"
        f"\nDrafted by  : Discharge Negotiator Agent (PatientOS)\n"
        f"Sent to     : {p.attending_doctor} for e-signature"
    )
    summary = store.create_summary(patient_id, content)

    doc = store.get_doctor(p.doctor_id)
    doc_phone = doc["phone"] if doc else "unknown"
    store.log_sms(p.attending_doctor, doc_phone,
                  f"Discharge summary ready for {p.name} ({patient_id}). "
                  f"Please review and sign: SUM/{summary.summary_id}")

    print(f"\n  [DISCHARGE SUMMARY DRAFTED]\n"
          f"  Patient : {p.name}\n"
          f"  ID      : {summary.summary_id}\n"
          f"  Sent to : {p.attending_doctor} for e-signature\n")

    return {
        "success":    True,
        "summary_id": summary.summary_id,
        "patient_id": patient_id,
        "status":     "draft — sent to doctor for e-signature",
        "sent_to":    p.attending_doctor,
    }


def _submit_insurance_preauth(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    reason     = inputs["reason"]
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    auth = store.submit_preauth(patient_id)

    print(f"\n  [INSURANCE PRE-AUTH SUBMITTED]\n"
          f"  Patient  : {p.name}\n"
          f"  Insurer  : {auth.provider}\n"
          f"  ICD-10   : {', '.join(auth.icd10_codes)}\n"
          f"  Auth No  : {auth.auth_number}\n"
          f"  Status   : {auth.status}\n")

    return {
        "success":     True,
        "auth_id":     auth.auth_id,
        "auth_number": auth.auth_number,
        "provider":    auth.provider,
        "status":      auth.status,
        "patient_id":  patient_id,
    }


def _message_agent(inputs: dict, store: DischargeStore) -> dict:
    to_agent     = inputs["to_agent"]
    patient_id   = inputs["patient_id"]
    message_type = inputs["message_type"]
    content      = inputs["content"]

    msg = store.send_agent_message(to_agent, patient_id, message_type, content)
    print(f"  [AGENT MSG → {to_agent}] [{message_type}] {content[:100]}")

    return {
        "success":    True,
        "message_id": msg.message_id,
        "to_agent":   to_agent,
        "patient_id": patient_id,
        "sent_at":    msg.sent_at,
    }


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
    print(f"  [SMS → {name} ({phone})]: {message}")

    return {
        "success":   True,
        "recipient": name,
        "phone":     phone,
        "message":   message,
    }


def _resolve_blocker(inputs: dict, store: DischargeStore) -> dict:
    blocker_id = inputs["blocker_id"]
    resolution = inputs["resolution"]
    ok = store.resolve_blocker(blocker_id, resolution)
    if not ok:
        return {"error": f"Blocker {blocker_id} not found"}
    print(f"  [BLOCKER RESOLVED] {blocker_id} — {resolution}")
    return {"success": True, "blocker_id": blocker_id, "resolution": resolution}


def _update_discharge_eta(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    eta        = inputs["eta"]
    reason     = inputs["reason"]
    ok = store.update_discharge_eta(patient_id, eta)
    if not ok:
        return {"error": f"Patient {patient_id} not found"}
    p = store.get_patient(patient_id)
    print(f"  [ETA UPDATE] {p.name} — expected discharge: {eta} ({reason})")
    return {"success": True, "patient_id": patient_id, "eta": eta, "reason": reason}


def _no_action(inputs: dict, store: DischargeStore) -> dict:
    patient_id = inputs["patient_id"]
    reason     = inputs["reason"]
    p = store.get_patient(patient_id)
    name = p.name if p else patient_id
    store._action_log.append({
        "timestamp":  datetime.now().isoformat(timespec="minutes"),
        "action":     "no_action",
        "patient_id": patient_id,
        "reason":     reason,
    })
    print(f"  [NOT READY] {name} ({patient_id}) — {reason}")
    return {"status": "no_action", "patient_id": patient_id, "reason": reason}