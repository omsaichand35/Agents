"""
Recovery Guardian tools.

These tools support the post-discharge recovery workflow, including silent
compliance-gap detection, patient reminders, doctor escalation, and recovery
closure actions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from family_comms import FamilyCommsService
from shared_state import OperationalEvent
try:
    from .recovery_store import RecoveryStore
except ImportError:
    from recovery_store import RecoveryStore


TOOL_DEFINITIONS = [
    {
        "name": "read_all_patients",
        "description": "Return all patients currently in post-discharge recovery.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_recovery",
        "description": "Return the full recovery record for one discharged patient.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "read_compliance_gaps",
        "description": "Analyze missed critical medication doses and return severity details.",
        "input_schema": {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "send_medication_reminder",
        "description": "Send a calm medication reminder to the patient and/or caregiver.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "time_of_day": {"type": "string"},
            },
            "required": ["patient_id", "time_of_day"],
        },
    },
    {
        "name": "notify_doctor",
        "description": "Escalate a recovery concern to the treating doctor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "moderate", "urgent", "emergency"]},
                "reason": {"type": "string"},
            },
            "required": ["patient_id", "severity", "reason"],
        },
    },
    {
        "name": "send_emergency_sms",
        "description": "Send a calm, specific emergency SMS to the patient or caregiver.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["patient_id", "message"],
        },
    },
    {
        "name": "book_emergency_appointment",
        "description": "Create a same-day or next-day follow-up appointment recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "urgency": {"type": "string"},
            },
            "required": ["patient_id", "urgency"],
        },
    },
    {
        "name": "mark_patient_recovered",
        "description": "Mark a patient as recovered and close out the recovery workflow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["patient_id", "summary"],
        },
    },
]


def execute_tool(name: str, inputs: Dict[str, Any], store: RecoveryStore) -> dict:
    try:
        if name == "read_all_patients":
            return _read_all_patients(store)
        if name == "read_patient_recovery":
            return _read_patient_recovery(inputs["patient_id"], store)
        if name == "read_compliance_gaps":
            return _read_compliance_gaps(inputs["patient_id"], store)
        if name == "send_medication_reminder":
            return _send_medication_reminder(inputs["patient_id"], inputs["time_of_day"], store)
        if name == "notify_doctor":
            return _notify_doctor(inputs, store)
        if name == "send_emergency_sms":
            return _send_emergency_sms(inputs["patient_id"], inputs["message"], store)
        if name == "book_emergency_appointment":
            return _book_emergency_appointment(inputs["patient_id"], inputs["urgency"], store)
        if name == "mark_patient_recovered":
            return _mark_patient_recovered(inputs["patient_id"], inputs["summary"], store)
        return {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        return {"error": str(exc)}


def _patient_to_dict(patient) -> dict:
    return {
        "patient_id": patient.patient_id,
        "name": patient.name,
        "age": patient.age,
        "phone": patient.phone,
        "caregiver_phone": patient.caregiver_phone,
        "language": patient.language,
        "discharge_date": patient.discharge_date,
        "diagnosis": patient.diagnosis,
        "treating_doctor": patient.treating_doctor,
        "doctor_phone": patient.doctor_phone,
        "follow_up_date": patient.follow_up_date,
        "ward": patient.ward,
        "recovery_day": patient.recovery_day,
        "status": patient.status,
        "medications": [
            {
                "med_id": med.med_id,
                "drug_name": med.drug_name,
                "dose": med.dose,
                "frequency": med.frequency,
                "duration_days": med.duration_days,
                "is_critical": med.is_critical,
            }
            for med in patient.medications
        ],
    }


def _read_all_patients(store: RecoveryStore) -> dict:
    return {"patients": [_patient_to_dict(patient) for patient in store.get_all_patients()]}


def _read_patient_recovery(patient_id: str, store: RecoveryStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    latest_checkin = store.get_latest_checkin(patient_id)
    compliance = store.analyze_compliance_gaps(patient_id)

    return {
        "patient": _patient_to_dict(patient),
        "latest_checkin": None if not latest_checkin else {
            "response_id": latest_checkin.response_id,
            "day": latest_checkin.day,
            "question": latest_checkin.question,
            "response_code": latest_checkin.response_code,
            "response_text": latest_checkin.response_text,
            "recorded_at": latest_checkin.recorded_at,
        },
        "compliance": compliance,
        "checkin_count": len(store.get_checkins(patient_id)),
    }


def _read_compliance_gaps(patient_id: str, store: RecoveryStore) -> dict:
    return store.analyze_compliance_gaps(patient_id)


def _send_medication_reminder(patient_id: str, time_of_day: str, store: RecoveryStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    medications = [
        {"drug": med.drug_name, "dose": med.dose}
        for med in patient.medications
    ]
    result = FamilyCommsService.send_medication_reminder(patient_id, medications, time_of_day)
    store.log_sms(patient_id, patient.phone, result["message"], sms_type="reminder")
    return {"success": True, "patient_id": patient_id, "message": result["message"]}


def _notify_doctor(inputs: dict, store: RecoveryStore) -> dict:
    patient_id = inputs["patient_id"]
    severity = inputs["severity"]
    reason = inputs["reason"]
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    escalation = store.create_escalation(
        patient_id=patient_id,
        day=patient.recovery_day,
        reason=reason,
        severity=severity,
        doctor_notified=True,
        patient_sms_sent=False,
    )
    OperationalEvent.emit(
        event="recovery.doctor_escalation",
        agent="recovery_guardian",
        patient_id=patient_id,
        priority=severity,
        next_action="doctor_followup",
        workflow_state=patient.status,
        detail={"reason": reason, "escalation_id": escalation.escalation_id},
    )
    return {
        "success": True,
        "escalation_id": escalation.escalation_id,
        "severity": severity,
        "doctor": patient.treating_doctor,
    }


def _send_emergency_sms(patient_id: str, message: str, store: RecoveryStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    FamilyCommsService.send_deterioration_notice(patient_id, severity="critical")
    store.log_sms(patient_id, patient.phone, message, sms_type="emergency")
    if patient.caregiver_phone:
        store.log_sms(patient_id, patient.caregiver_phone, message, sms_type="emergency_caregiver")
    OperationalEvent.emit(
        event="recovery.emergency_sms_sent",
        agent="recovery_guardian",
        patient_id=patient_id,
        priority="critical",
        next_action="doctor_notification",
        workflow_state=patient.status,
        detail={"message": message},
    )
    return {"success": True, "patient_id": patient_id, "message": message}


def _book_emergency_appointment(patient_id: str, urgency: str, store: RecoveryStore) -> dict:
    patient = store.get_patient(patient_id)
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    today = datetime.now()
    eta = today + timedelta(hours=4 if urgency == "urgent" else 24)
    appointment = {
        "patient_id": patient_id,
        "urgency": urgency,
        "recommended_for": eta.isoformat(timespec="minutes"),
        "doctor": patient.treating_doctor,
    }
    OperationalEvent.emit(
        event="recovery.emergency_appointment_booked",
        agent="recovery_guardian",
        patient_id=patient_id,
        priority=urgency,
        next_action="patient_followup",
        workflow_state=patient.status,
        detail={"appointment": appointment},
    )
    return {"success": True, "appointment": appointment}


def _mark_patient_recovered(patient_id: str, summary: str, store: RecoveryStore) -> dict:
    ok = store.update_status(patient_id, "recovered")
    if not ok:
        return {"error": f"Patient {patient_id} not found"}
    OperationalEvent.emit(
        event="recovery.closed",
        agent="recovery_guardian",
        patient_id=patient_id,
        priority="info",
        next_action="archive_case",
        workflow_state="recovered",
        detail={"summary": summary},
    )
    return {"success": True, "patient_id": patient_id, "summary": summary}