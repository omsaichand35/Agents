"""
patient_store.py
================
In-memory patient store simulating a hospital queue database.
In production this would be backed by a real DB (PostgreSQL, etc.)
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime


@dataclass
class Patient:
    id: str
    name: str
    age: int
    token: str                    # Original check-in token (e.g. A001)
    chief_complaint: str
    arrived_at: str               # HH:MM
    acuity_score: int = 0         # Filled in by agent (1–10)
    position: int = 0             # Current queue position (1 = next)
    phone: str = ""
    vitals: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self):
        return asdict(self)


class PatientStore:
    """
    Thread-safe (enough for single-agent use) in-memory patient queue.
    Simulates the hospital's waiting-area queue.
    """

    def __init__(self):
        self._patients: List[Patient] = [
            Patient(
                id="P001",
                name="Ravi S.",
                age=35,
                token="A001",
                chief_complaint="Sprained ankle — mild swelling, no deformity, pain 4/10",
                arrived_at="08:02",
                position=1,
                phone="+91-98765-11111",
                vitals={"bp": "118/76", "hr": 78, "spo2": 99, "temp": 98.4},
            ),
            Patient(
                id="P002",
                name="Meena P.",
                age=70,
                token="A002",
                chief_complaint="Chest pain — crushing, radiating to left arm, diaphoresis, onset 30 min ago",
                arrived_at="08:17",
                position=2,
                phone="+91-98765-43210",
                vitals={"bp": "160/95", "hr": 102, "spo2": 94, "temp": 98.9},
            ),
            Patient(
                id="P003",
                name="Arjun K.",
                age=45,
                token="A003",
                chief_complaint="Fever 102°F for 3 days, productive cough with yellow sputum",
                arrived_at="08:25",
                position=3,
                phone="+91-98765-22222",
                vitals={"bp": "128/82", "hr": 95, "spo2": 96, "temp": 102.1},
            ),
            Patient(
                id="P004",
                name="Priya T.",
                age=28,
                token="A004",
                chief_complaint="Mild headache and nausea since morning, no fever",
                arrived_at="08:31",
                position=4,
                phone="+91-98765-33333",
                vitals={"bp": "112/70", "hr": 72, "spo2": 98, "temp": 98.2},
            ),
        ]
        self._sms_log: List[dict] = []
        self._doctor_log: List[dict] = []
        self._action_log: List[dict] = []

    # ── Queue access ────────────────────────────────────────────────────────

    def get_queue(self) -> List[Patient]:
        return sorted(self._patients, key=lambda p: p.position)

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        for p in self._patients:
            if p.id == patient_id:
                return p
        return None

    def add_patient(self, patient: Patient) -> None:
        patient.position = len(self._patients) + 1
        self._patients.append(patient)

    def remove_patient(self, patient_id: str) -> bool:
        before = len(self._patients)
        self._patients = [p for p in self._patients if p.id != patient_id]
        self._renumber()
        return len(self._patients) < before

    def reshuffle(self, ordered_ids: List[str]) -> dict:
        """Assign new positions based on agent-supplied ordered list of patient IDs."""
        id_to_patient = {p.id: p for p in self._patients}
        old_positions = {p.id: p.position for p in self._patients}

        moved = []
        for new_pos, pid in enumerate(ordered_ids, start=1):
            if pid in id_to_patient:
                patient = id_to_patient[pid]
                if patient.position != new_pos:
                    moved.append({
                        "patient_id": pid,
                        "name": patient.name,
                        "old_position": patient.position,
                        "new_position": new_pos,
                    })
                patient.position = new_pos

        self._action_log.append({
            "type": "reshuffle",
            "timestamp": datetime.now().isoformat(),
            "new_order": ordered_ids,
            "moved": moved,
        })
        return {"success": True, "moved": moved}

    def _renumber(self):
        for i, p in enumerate(sorted(self._patients, key=lambda x: x.position), start=1):
            p.position = i

    # ── Communication logs ──────────────────────────────────────────────────

    def log_sms(self, patient_id: str, phone: str, message: str) -> None:
        self._sms_log.append({
            "timestamp": datetime.now().isoformat(),
            "patient_id": patient_id,
            "phone": phone,
            "message": message,
        })

    def log_doctor_notification(self, message: str, priority: str) -> None:
        self._doctor_log.append({
            "timestamp": datetime.now().isoformat(),
            "priority": priority,
            "message": message,
        })

    # ── Audit ───────────────────────────────────────────────────────────────

    def get_sms_log(self) -> List[dict]:
        return self._sms_log

    def get_doctor_log(self) -> List[dict]:
        return self._doctor_log

    def get_action_log(self) -> List[dict]:
        return self._action_log