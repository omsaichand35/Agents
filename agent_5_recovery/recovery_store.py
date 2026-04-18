"""
recovery_store.py
=================
In-memory store for the Recovery Guardian Agent.
Mirrors the style of all previous PatientOS agent stores.

Simulates:
  - Discharged patients with home medication schedules
  - Daily check-in responses (patient replies to SMS)
  - Medication compliance log (what was actually taken)
  - Escalation log (when agent alerts doctor)
  - SMS log (every outbound message)
  - Audit log

In production: backed by PostgreSQL / hospital EMR.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import uuid


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class HomeMedication:
    med_id:           str
    patient_id:       str
    drug_name:        str
    dose:             str
    frequency:        str      # "morning" | "morning_night" | "thrice_daily"
    duration_days:    int
    start_date:       str
    food_instruction: str
    is_critical:      bool = False  # antibiotics, cardiac drugs — MUST NOT be missed


@dataclass
class DischargedPatient:
    patient_id:      str
    name:            str
    age:             int
    phone:           str
    caregiver_phone: str
    language:        str       # english | tamil | hindi
    discharge_date:  str
    diagnosis:       str
    treating_doctor: str
    doctor_phone:    str
    follow_up_date:  str
    ward:            str
    recovery_day:    int = 1
    status:          str = "recovering"  # recovering | recovered | escalated
    medications:     List[HomeMedication] = field(default_factory=list)


@dataclass
class CheckInResponse:
    response_id:   str
    patient_id:    str
    day:           int
    question:      str
    response_code: str   # "1" better | "2" same | "3" worse
    response_text: str
    follow_up_q:   str = ""
    follow_up_ans: str = ""
    recorded_at:   str = ""
    action_taken:  str = ""


@dataclass
class EscalationRecord:
    escalation_id:    str
    patient_id:       str
    day:              int
    reason:           str
    severity:         str   # urgent | emergency
    doctor_notified:  bool
    patient_sms_sent: bool
    recorded_at:      str


# ── Recovery Store ────────────────────────────────────────────────────────────

class RecoveryStore:
    """
    Three discharged patients pre-loaded with distinct post-discharge scenarios:

      REC-001  Meena K.  (58F) — Day 4, latest check-in says WORSE — fever returning
      REC-002  Ravi S.   (45M) — Day 2, doing well — stable recovery
      REC-003  Arjun P.  (62M) — Day 6, missed 2 consecutive critical cardiac doses
    """

    def __init__(self):
        today     = datetime.now().date()
        yesterday = today - timedelta(days=1)

        # ── Patients ──────────────────────────────────────────────────────
        self._patients: Dict[str, DischargedPatient] = {

            "REC-001": DischargedPatient(
                patient_id="REC-001",
                name="Meena Krishnan",
                age=58,
                phone="+91-98765-00001",
                caregiver_phone="+91-98765-00002",
                language="tamil",
                discharge_date=(today - timedelta(days=4)).isoformat(),
                diagnosis="Community-acquired pneumonia — treated and discharged",
                treating_doctor="Dr. R. Sharma",
                doctor_phone="+91-98001-11111",
                follow_up_date=(today + timedelta(days=3)).isoformat(),
                ward="Ward 3",
                recovery_day=4,
                medications=[
                    HomeMedication("HM001", "REC-001", "Azithromycin 500mg",  "500mg",
                                   "morning",       5,  today.isoformat(), "after food",  True),
                    HomeMedication("HM002", "REC-001", "Paracetamol 500mg",   "500mg",
                                   "morning_night", 5,  today.isoformat(), "after food",  False),
                    HomeMedication("HM003", "REC-001", "Vitamin C 500mg",     "500mg",
                                   "morning",       10, today.isoformat(), "with water",  False),
                ],
            ),

            "REC-002": DischargedPatient(
                patient_id="REC-002",
                name="Ravi Shankar",
                age=45,
                phone="+91-98765-00003",
                caregiver_phone="",
                language="english",
                discharge_date=yesterday.isoformat(),
                diagnosis="Post-surgical knee replacement — Day 2 recovery at home",
                treating_doctor="Dr. R. Sharma",
                doctor_phone="+91-98001-11111",
                follow_up_date=(today + timedelta(days=5)).isoformat(),
                ward="Ward 3",
                recovery_day=2,
                medications=[
                    HomeMedication("HM004", "REC-002", "Amoxicillin 500mg", "500mg",
                                   "thrice_daily", 7, yesterday.isoformat(), "after food", True),
                    HomeMedication("HM005", "REC-002", "Ibuprofen 400mg",   "400mg",
                                   "thrice_daily", 5, yesterday.isoformat(), "after food", False),
                ],
            ),

            "REC-003": DischargedPatient(
                patient_id="REC-003",
                name="Arjun Pillai",
                age=62,
                phone="+91-98765-00005",
                caregiver_phone="+91-98765-00006",
                language="english",
                discharge_date=(today - timedelta(days=6)).isoformat(),
                diagnosis="Post-cardiac catheterisation — stable, discharged on lifelong medications",
                treating_doctor="Dr. P. Mehta",
                doctor_phone="+91-98001-22222",
                follow_up_date=(today + timedelta(days=1)).isoformat(),
                ward="ICU",
                recovery_day=6,
                medications=[
                    HomeMedication("HM006", "REC-003", "Aspirin 75mg",        "75mg",
                                   "morning",       30, (today - timedelta(days=6)).isoformat(),
                                   "after food", True),
                    HomeMedication("HM007", "REC-003", "Atorvastatin 40mg",   "40mg",
                                   "morning",       30, (today - timedelta(days=6)).isoformat(),
                                   "after food", True),
                    HomeMedication("HM008", "REC-003", "Metoprolol 25mg",     "25mg",
                                   "morning_night", 30, (today - timedelta(days=6)).isoformat(),
                                   "after food", True),
                ],
            ),
        }

        # ── Check-in history ──────────────────────────────────────────────
        # Meena: Days 1-2 better, Day 3 same, Day 4 WORSE (today — agent handles this)
        # Ravi:  Day 1 better, stable
        # Arjun: Days 1-5 all "better" — but compliance log shows missed critical doses

        self._checkins: List[CheckInResponse] = [
            CheckInResponse("CI001", "REC-001", 1, "How are you feeling?",
                            "1", "Much better",
                            recorded_at=(today - timedelta(days=3)).isoformat()),
            CheckInResponse("CI002", "REC-001", 2, "How are you feeling?",
                            "1", "Much better",
                            recorded_at=(today - timedelta(days=2)).isoformat()),
            CheckInResponse("CI003", "REC-001", 3, "How are you feeling?",
                            "2", "Same as discharge",
                            recorded_at=yesterday.isoformat()),
            CheckInResponse("CI004", "REC-001", 4, "How are you feeling?",
                            "3", "Getting worse",
                            recorded_at=datetime.now().isoformat(timespec="minutes")),

            CheckInResponse("CI005", "REC-002", 1, "How are you feeling?",
                            "1", "Much better",
                            recorded_at=yesterday.isoformat()),

            CheckInResponse("CI006", "REC-003", 1, "How are you feeling?",
                            "1", "Much better", recorded_at=(today - timedelta(days=5)).isoformat()),
            CheckInResponse("CI007", "REC-003", 2, "How are you feeling?",
                            "1", "Much better", recorded_at=(today - timedelta(days=4)).isoformat()),
            CheckInResponse("CI008", "REC-003", 3, "How are you feeling?",
                            "1", "Much better", recorded_at=(today - timedelta(days=3)).isoformat()),
            CheckInResponse("CI009", "REC-003", 4, "How are you feeling?",
                            "1", "Much better", recorded_at=(today - timedelta(days=2)).isoformat()),
            CheckInResponse("CI010", "REC-003", 5, "How are you feeling?",
                            "1", "Much better", recorded_at=yesterday.isoformat()),
        ]

        # ── Medication compliance log ──────────────────────────────────────
        # Arjun missed 2 consecutive mornings of critical cardiac meds
        # Agent must detect this even though his check-ins say "better"

        self._compliance_log: List[dict] = [
            {"patient_id": "REC-003", "med_id": "HM006", "drug": "Aspirin 75mg",
             "date": (today - timedelta(days=1)).isoformat(), "status": "missed"},
            {"patient_id": "REC-003", "med_id": "HM007", "drug": "Atorvastatin 40mg",
             "date": (today - timedelta(days=1)).isoformat(), "status": "missed"},
            {"patient_id": "REC-003", "med_id": "HM006", "drug": "Aspirin 75mg",
             "date": today.isoformat(), "status": "missed"},
            {"patient_id": "REC-003", "med_id": "HM007", "drug": "Atorvastatin 40mg",
             "date": today.isoformat(), "status": "missed"},
        ]

        self._escalations: List[EscalationRecord] = []
        self._sms_log:     List[dict]              = []
        self._action_log:  List[dict]              = []

    # ── Patients ──────────────────────────────────────────────────────────

    def get_all_patients(self) -> List[DischargedPatient]:
        return [p for p in self._patients.values() if p.status == "recovering"]

    def get_patient(self, patient_id: str) -> Optional[DischargedPatient]:
        return self._patients.get(patient_id)

    def update_status(self, patient_id: str, status: str) -> bool:
        p = self._patients.get(patient_id)
        if not p:
            return False
        p.status = status
        return True

    # ── Check-ins ─────────────────────────────────────────────────────────

    def get_checkins(self, patient_id: str) -> List[CheckInResponse]:
        return [c for c in self._checkins if c.patient_id == patient_id]

    def get_latest_checkin(self, patient_id: str) -> Optional[CheckInResponse]:
        rows = self.get_checkins(patient_id)
        return rows[-1] if rows else None

    def add_checkin(self, checkin: CheckInResponse) -> None:
        self._checkins.append(checkin)
        self._action_log.append({
            "timestamp":  datetime.now().isoformat(timespec="minutes"),
            "action":     "checkin_recorded",
            "patient_id": checkin.patient_id,
            "response":   checkin.response_code,
        })

    # ── Compliance ────────────────────────────────────────────────────────

    def get_missed_critical_doses(self, patient_id: str) -> List[dict]:
        return [
            c for c in self._compliance_log
            if c["patient_id"] == patient_id and c["status"] == "missed"
        ]

    # ── Escalations ───────────────────────────────────────────────────────

    def create_escalation(
        self, patient_id: str, day: int, reason: str,
        severity: str, doctor_notified: bool = True, patient_sms_sent: bool = True,
    ) -> EscalationRecord:
        esc = EscalationRecord(
            escalation_id=f"ESC-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id, day=day, reason=reason,
            severity=severity, doctor_notified=doctor_notified,
            patient_sms_sent=patient_sms_sent,
            recorded_at=datetime.now().isoformat(timespec="minutes"),
        )
        self._escalations.append(esc)
        self._action_log.append({
            "timestamp": esc.recorded_at, "action": "escalation",
            "patient_id": patient_id, "severity": severity, "reason": reason,
        })
        return esc

    # ── SMS ───────────────────────────────────────────────────────────────

    def log_sms(self, patient_id: str, phone: str, message: str, sms_type: str) -> None:
        self._sms_log.append({
            "timestamp":  datetime.now().isoformat(timespec="minutes"),
            "patient_id": patient_id, "phone": phone,
            "sms_type":   sms_type,   "message": message,
        })
        print(f"  [SMS/{sms_type} -> {phone}] {message[:110]}")

    # ── Audit ─────────────────────────────────────────────────────────────

    def get_escalation_log(self) -> List[EscalationRecord]: return self._escalations
    def get_sms_log(self)        -> List[dict]:              return self._sms_log
    def get_action_log(self)     -> List[dict]:              return self._action_log