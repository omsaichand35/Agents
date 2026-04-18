"""
tools.py
========
Tool definitions and executors for the Recovery Guardian Agent.
Follows the exact same pattern as tools.py in agents 1, 2, and 3.

Tools:
  read_all_patients         — list every patient currently in post-discharge recovery
  read_patient_recovery     — full discharge record, medications, check-in history
  read_compliance_gaps      — detect missed critical medication doses at home
  send_checkin_sms          — send the daily "how are you feeling?" check-in SMS
  send_medication_reminder  — send morning/evening medication reminder SMS
  send_emergency_sms        — urgent SMS to patient + caregiver when condition worsens
  notify_doctor             — alert the treating doctor with clinical context
  book_emergency_appointment — create an urgent same-day appointment slot
  mark_patient_recovered    — close the recovery loop when course is complete
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timedelta
from recovery_store import RecoveryStore, CheckInResponse, EscalationRecord
import uuid

# ── Medication frequency -> human readable times ──────────────────────────
FREQ_TIMES = {
    "morning":       "8:00 AM",
    "morning_night": "8:00 AM and 9:00 PM",
    "thrice_daily":  "8:00 AM, 2:00 PM and 9:00 PM",
}

# ── Tool schemas ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_all_patients",
        "description": (
            "Returns every patient currently in post-discharge home recovery. "
            "Call this at the start of every cycle to know who to assess today. "
            "Each entry includes patient_id, name, age, diagnosis, recovery_day, "
            "language, phone, caregiver_phone, follow_up_date."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_patient_recovery",
        "description": (
            "Returns the complete post-discharge record for one patient: "
            "demographics, diagnosis, treating doctor, all home medications with "
            "dose/frequency/duration, full check-in history with response codes, "
            "and recovery day count. "
            "Use this to understand what medications they should be taking and "
            "how they have been responding since discharge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient ID e.g. REC-001"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "read_compliance_gaps",
        "description": (
            "Scans the medication compliance log for a patient and returns any "
            "critical doses that were missed at home. "
            "This is how the agent catches silent non-compliance — patients who "
            "say they are 'fine' in check-ins but are not actually taking their medications. "
            "Returns a list of missed doses with drug name, date, and is_critical flag."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient ID to check compliance for"},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "send_checkin_sms",
        "description": (
            "Send the daily recovery check-in SMS to a patient. "
            "The message asks how they are feeling and gives three reply options: "
            "1 = Much better, 2 = Same as discharge, 3 = Getting worse. "
            "Record the patient's latest response if already received. "
            "The agent reads the response code from the check-in history and decides "
            "what action to take next."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "day": {"type": "integer", "description": "Recovery day number"},
            },
            "required": ["patient_id", "day"],
        },
    },
    {
        "name": "send_medication_reminder",
        "description": (
            "Send a personalised medication reminder SMS to the patient listing "
            "every medicine they need to take, with dose, timing, and food instructions. "
            "If the patient has a caregiver number, send to both. "
            "Include a motivational note with day progress (e.g. 'Day 3 of 5 — well done!')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "time_of_day": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "night"],
                    "description": "Which reminder set to send",
                },
            },
            "required": ["patient_id", "time_of_day"],
        },
    },
    {
        "name": "send_emergency_sms",
        "description": (
            "Send an urgent SMS to the patient AND caregiver when the patient "
            "reports worsening symptoms or the agent detects a critical compliance gap. "
            "The message should be calm, reassuring, and give a clear next action. "
            "Always call notify_doctor alongside this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why this emergency SMS is being sent"},
                "instruction": {
                    "type": "string",
                    "description": "Clear instruction for the patient — what to do right now",
                },
                "severity": {
                    "type": "string",
                    "enum": ["urgent", "emergency"],
                    "description": "urgent = come to hospital today | emergency = call ambulance now",
                },
            },
            "required": ["patient_id", "reason", "instruction", "severity"],
        },
    },
    {
        "name": "notify_doctor",
        "description": (
            "Alert the treating doctor about a patient's worsening condition or "
            "critical compliance gap. Provide full clinical context — what the patient "
            "reported, what the trend has been, what action you already took, "
            "and what you need from the doctor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["routine", "urgent", "critical"],
                },
                "clinical_summary": {
                    "type": "string",
                    "description": (
                        "Full context for the doctor: patient name/age/diagnosis, "
                        "check-in trend, what they reported today, what action you took, "
                        "and what you recommend."
                    ),
                },
            },
            "required": ["patient_id", "priority", "clinical_summary"],
        },
    },
    {
        "name": "book_emergency_appointment",
        "description": (
            "Create an urgent same-day or next-day appointment for a patient "
            "who has reported worsening symptoms. "
            "Returns the appointment slot and sends confirmation SMS to patient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "urgency": {
                    "type": "string",
                    "enum": ["today", "tomorrow"],
                    "description": "How soon the patient needs to be seen",
                },
                "reason": {"type": "string", "description": "Reason for the urgent appointment"},
            },
            "required": ["patient_id", "urgency", "reason"],
        },
    },
    {
        "name": "mark_patient_recovered",
        "description": (
            "Mark a patient's recovery as complete when their medication course has ended "
            "and their last check-in confirms they are doing well. "
            "Sends a final congratulatory SMS and reminds them of their follow-up date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "summary": {
                    "type": "string",
                    "description": "Brief summary of their recovery journey",
                },
            },
            "required": ["patient_id", "summary"],
        },
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict[str, Any], store: RecoveryStore) -> dict:
    try:
        dispatch = {
            "read_all_patients":          lambda: _read_all_patients(store),
            "read_patient_recovery":      lambda: _read_patient_recovery(inputs["patient_id"], store),
            "read_compliance_gaps":       lambda: _read_compliance_gaps(inputs["patient_id"], store),
            "send_checkin_sms":           lambda: _send_checkin_sms(inputs, store),
            "send_medication_reminder":   lambda: _send_medication_reminder(inputs, store),
            "send_emergency_sms":         lambda: _send_emergency_sms(inputs, store),
            "notify_doctor":              lambda: _notify_doctor(inputs, store),
            "book_emergency_appointment": lambda: _book_emergency_appointment(inputs, store),
            "mark_patient_recovered":     lambda: _mark_patient_recovered(inputs, store),
        }
        if name not in dispatch:
            return {"error": f"Unknown tool: {name}"}
        return dispatch[name]()
    except Exception as e:
        return {"error": str(e)}


# ── Handlers ──────────────────────────────────────────────────────────────

def _read_all_patients(store: RecoveryStore) -> dict:
    patients = store.get_all_patients()
    return {
        "total_recovering": len(patients),
        "patients": [
            {
                "patient_id":     p.patient_id,
                "name":           p.name,
                "age":            p.age,
                "diagnosis":      p.diagnosis,
                "recovery_day":   p.recovery_day,
                "language":       p.language,
                "phone":          p.phone,
                "caregiver_phone": p.caregiver_phone,
                "discharge_date": p.discharge_date,
                "follow_up_date": p.follow_up_date,
                "treating_doctor": p.treating_doctor,
                "total_medications": len(p.medications),
            }
            for p in patients
        ],
    }


def _read_patient_recovery(patient_id: str, store: RecoveryStore) -> dict:
    p = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    checkins = store.get_checkins(patient_id)
    return {
        "patient_id":     p.patient_id,
        "name":           p.name,
        "age":            p.age,
        "phone":          p.phone,
        "caregiver_phone": p.caregiver_phone,
        "language":       p.language,
        "diagnosis":      p.diagnosis,
        "treating_doctor": p.treating_doctor,
        "doctor_phone":   p.doctor_phone,
        "discharge_date": p.discharge_date,
        "follow_up_date": p.follow_up_date,
        "recovery_day":   p.recovery_day,
        "status":         p.status,
        "medications": [
            {
                "med_id":           m.med_id,
                "drug_name":        m.drug_name,
                "dose":             m.dose,
                "frequency":        m.frequency,
                "duration_days":    m.duration_days,
                "start_date":       m.start_date,
                "food_instruction": m.food_instruction,
                "is_critical":      m.is_critical,
            }
            for m in p.medications
        ],
        "checkin_history": [
            {
                "day":           c.day,
                "response_code": c.response_code,
                "response_text": c.response_text,
                "recorded_at":   c.recorded_at,
                "action_taken":  c.action_taken,
            }
            for c in checkins
        ],
        "latest_checkin_code": checkins[-1].response_code if checkins else "none",
    }


def _read_compliance_gaps(patient_id: str, store: RecoveryStore) -> dict:
    missed = store.get_missed_critical_doses(patient_id)
    p      = store.get_patient(patient_id)
    return {
        "patient_id":      patient_id,
        "patient_name":    p.name if p else patient_id,
        "missed_count":    len(missed),
        "has_critical_gap": len(missed) > 0,
        "missed_doses": missed,
        "assessment": (
            "CRITICAL — patient has missed critical medications. "
            "Risk of treatment failure or relapse."
            if len(missed) >= 2 else
            "WARNING — one missed dose detected." if len(missed) == 1 else
            "No compliance gaps detected."
        ),
    }


def _send_checkin_sms(inputs: dict, store: RecoveryStore) -> dict:
    patient_id = inputs["patient_id"]
    day        = inputs["day"]
    p          = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    latest = store.get_latest_checkin(patient_id)
    response_code = latest.response_code if latest else "none"
    response_text = latest.response_text if latest else "No response yet"

    message = (
        f"Good morning {p.name.split()[0]}! "
        f"City General Hospital is checking in on you (Day {day}). "
        f"How are you feeling today? "
        f"Reply: 1 - Much better | 2 - Same as discharge | 3 - Getting worse. "
        f"Your reply goes directly to {p.treating_doctor}."
    )

    store.log_sms(patient_id, p.phone, message, "checkin")

    return {
        "success":             True,
        "patient_id":          patient_id,
        "day":                 day,
        "sms_sent_to":         p.phone,
        "latest_response_code": response_code,
        "latest_response_text": response_text,
        "message_preview":     message[:100],
    }


def _send_medication_reminder(inputs: dict, store: RecoveryStore) -> dict:
    patient_id  = inputs["patient_id"]
    time_of_day = inputs["time_of_day"]
    p           = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    # Build medicine list for this time slot
    meds_due = []
    for m in p.medications:
        if time_of_day == "morning" and m.frequency in ["morning", "morning_night", "thrice_daily"]:
            meds_due.append(m)
        elif time_of_day == "afternoon" and m.frequency == "thrice_daily":
            meds_due.append(m)
        elif time_of_day == "night" and m.frequency in ["morning_night", "thrice_daily"]:
            meds_due.append(m)

    if not meds_due:
        return {"success": True, "message": "No medications due at this time", "patient_id": patient_id}

    med_lines = "\n".join(
        [f"{i+1}. {m.drug_name} — 1 tablet {m.food_instruction}"
         for i, m in enumerate(meds_due)]
    )

    # Find max duration to show progress
    max_dur  = max(m.duration_days for m in p.medications) if p.medications else 7
    day_text = f"Day {p.recovery_day} of {max_dur}"

    message = (
        f"Good {'morning' if time_of_day == 'morning' else 'evening'} {p.name.split()[0]}! "
        f"Time for your {time_of_day} medicines ({day_text}):\n"
        f"{med_lines}\n"
        f"Questions? Call City General: 044-XXXX-XXXX"
    )

    store.log_sms(patient_id, p.phone, message, f"med_reminder_{time_of_day}")
    if p.caregiver_phone:
        store.log_sms(patient_id, p.caregiver_phone,
                      f"[For {p.name.split()[0]}] " + message, f"caregiver_reminder")

    return {
        "success":          True,
        "patient_id":       patient_id,
        "time_of_day":      time_of_day,
        "medications_sent": [m.drug_name for m in meds_due],
        "sent_to_caregiver": bool(p.caregiver_phone),
    }


def _send_emergency_sms(inputs: dict, store: RecoveryStore) -> dict:
    patient_id  = inputs["patient_id"]
    reason      = inputs["reason"]
    instruction = inputs["instruction"]
    severity    = inputs["severity"]
    p           = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    if severity == "emergency":
        message = (
            f"URGENT — City General Hospital: {p.name.split()[0]}, "
            f"we are concerned about your health. {instruction} "
            f"If you cannot reach us, call 108 immediately."
        )
    else:
        message = (
            f"City General Hospital: {p.name.split()[0]}, "
            f"based on your check-in today, {p.treating_doctor} would like to see you. "
            f"{instruction}"
        )

    store.log_sms(patient_id, p.phone, message, f"emergency_{severity}")
    if p.caregiver_phone:
        caregiver_msg = (
            f"[Family of {p.name}] City General Hospital: "
            f"Please ensure {p.name.split()[0]} follows these instructions — {instruction}"
        )
        store.log_sms(patient_id, p.caregiver_phone, caregiver_msg, "caregiver_emergency")

    esc = store.create_escalation(
        patient_id=patient_id,
        day=p.recovery_day,
        reason=reason,
        severity=severity,
        doctor_notified=False,   # doctor is notified separately via notify_doctor
        patient_sms_sent=True,
    )

    store.update_status(patient_id, "escalated")

    return {
        "success":         True,
        "escalation_id":   esc.escalation_id,
        "patient_id":      patient_id,
        "severity":        severity,
        "sms_sent_to":     p.phone,
        "caregiver_notified": bool(p.caregiver_phone),
    }


def _notify_doctor(inputs: dict, store: RecoveryStore) -> dict:
    patient_id = inputs["patient_id"]
    priority   = inputs["priority"]
    summary    = inputs["clinical_summary"]
    p          = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    print(f"\n  [DOCTOR ALERT — {priority.upper()} -> {p.treating_doctor} ({p.doctor_phone})]")
    print(f"  {summary}\n")

    store._action_log.append({
        "timestamp":  datetime.now().isoformat(timespec="minutes"),
        "action":     "doctor_notified",
        "patient_id": patient_id,
        "priority":   priority,
        "summary":    summary[:120],
    })

    return {
        "success":         True,
        "doctor":          p.treating_doctor,
        "phone":           p.doctor_phone,
        "priority":        priority,
        "patient_id":      patient_id,
        "delivered":       "pager + SMS (simulated)",
    }


def _book_emergency_appointment(inputs: dict, store: RecoveryStore) -> dict:
    patient_id = inputs["patient_id"]
    urgency    = inputs["urgency"]
    reason     = inputs["reason"]
    p          = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    today = datetime.now().date()
    if urgency == "today":
        slot_date = today
        slot_time = "3:30 PM"
    else:
        slot_date = today + timedelta(days=1)
        slot_time = "10:00 AM"

    appt_id = f"APPT-{uuid.uuid4().hex[:6].upper()}"
    confirm_msg = (
        f"{p.name.split()[0]}, your urgent appointment has been booked: "
        f"{p.treating_doctor} | {slot_date.strftime('%d %b %Y')} at {slot_time}. "
        f"Please carry your discharge summary and all current medications."
    )

    store.log_sms(patient_id, p.phone, confirm_msg, "appt_confirmation")

    store._action_log.append({
        "timestamp":  datetime.now().isoformat(timespec="minutes"),
        "action":     "appointment_booked",
        "patient_id": patient_id,
        "slot":       f"{slot_date} {slot_time}",
        "reason":     reason,
    })

    return {
        "success":       True,
        "appointment_id": appt_id,
        "patient_id":    patient_id,
        "date":          str(slot_date),
        "time":          slot_time,
        "doctor":        p.treating_doctor,
        "reason":        reason,
    }


def _mark_patient_recovered(inputs: dict, store: RecoveryStore) -> dict:
    patient_id = inputs["patient_id"]
    summary    = inputs["summary"]
    p          = store.get_patient(patient_id)
    if not p:
        return {"error": f"Patient {patient_id} not found"}

    store.update_status(patient_id, "recovered")

    message = (
        f"Congratulations {p.name.split()[0]}! "
        f"You have completed your recovery course. "
        f"City General Hospital is proud of your progress. "
        f"Please remember your follow-up appointment: {p.follow_up_date} with {p.treating_doctor}. "
        f"Take care!"
    )

    store.log_sms(patient_id, p.phone, message, "recovery_complete")

    store._action_log.append({
        "timestamp":  datetime.now().isoformat(timespec="minutes"),
        "action":     "recovery_complete",
        "patient_id": patient_id,
        "summary":    summary,
    })

    print(f"\n  [RECOVERY COMPLETE] {p.name} ({patient_id}) — {summary}")

    return {
        "success":    True,
        "patient_id": patient_id,
        "status":     "recovered",
        "summary":    summary,
    }