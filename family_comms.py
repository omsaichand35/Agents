"""
Family communication helpers for HospitalOS workflows.

This module keeps caretaker and patient-facing messages operational, calm,
and non-diagnostic. It reads shared workflow state so messages stay aligned
with the current hospital workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from shared_state import ops


class FamilyCommsService:
    """Centralized family and patient communication helpers."""

    @staticmethod
    def send_discharge_eta(patient_id: str, eta: str, doctor_name: str) -> dict:
        state = ops.get(patient_id)
        if not state:
            return {"sent": False, "error": "unknown_patient"}

        message = (
            f"Dear family of {state.name}, the care team expects discharge by {eta}. "
            f"Please remain available. Contact: {doctor_name}."
        )
        state.family_notified = True
        state.family_notified_at = datetime.now().isoformat(timespec="seconds")
        state.last_sms_to_patient = message
        print(f"  [FAMILY SMS] {message}")
        return {"sent": True, "message": message}

    @staticmethod
    def send_deterioration_notice(patient_id: str, severity: str) -> dict:
        state = ops.get(patient_id)
        if not state:
            return {"sent": False, "error": "unknown_patient"}

        if severity in {"high", "critical"}:
            message = (
                f"Important update for family of {state.name}: the care team has escalated "
                f"the review and the doctor is involved. We will share updates shortly."
            )
        else:
            message = (
                f"Update for family of {state.name}: the care team has noticed a change in "
                f"status and is monitoring closely."
            )

        state.family_notified = True
        state.family_notified_at = datetime.now().isoformat(timespec="seconds")
        state.last_sms_to_patient = message
        print(f"  [FAMILY SMS / {severity.upper()}] {message}")
        return {"sent": True, "message": message}

    @staticmethod
    def send_discharge_delay(patient_id: str, reason: str) -> dict:
        state = ops.get(patient_id)
        if not state:
            return {"sent": False, "error": "unknown_patient"}

        message = (
            f"Update for family of {state.name}: discharge is temporarily delayed because {reason}. "
            f"We will share a new estimate soon."
        )
        state.family_notified = True
        state.family_notified_at = datetime.now().isoformat(timespec="seconds")
        state.last_sms_to_patient = message
        print(f"  [FAMILY SMS / DELAY] {message}")
        return {"sent": True, "message": message}

    @staticmethod
    def send_medication_reminder(patient_id: str, medications: List[dict], time_of_day: str) -> dict:
        state = ops.get(patient_id)
        if not state:
            return {"sent": False, "error": "unknown_patient"}

        med_list = ", ".join(f"{m.get('drug', '')} {m.get('dose', '')}".strip() for m in medications)
        message = (
            f"Good {time_of_day}, {state.name}. Please take your medications: {med_list}. "
            f"If already taken, please ignore this reminder."
        )
        state.last_sms_to_patient = message
        print(f"  [PATIENT SMS / {time_of_day.upper()}] {message}")
        return {"sent": True, "message": message}