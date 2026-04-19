"""
patient_store.py
================
In-memory patient store for the Deterioration Sentinel Agent.
Mirrors the style of PatientStore (agent_1) and CareStore (agent_2).

Simulates:
  - Admitted patients with vitals history
  - Alert log (what the agent fires)
  - Inter-agent message bus (Sentinel -> other agents)
  - Audit log

In production: backed by PostgreSQL / hospital EMR.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import uuid


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class VitalReading:
    vital_id:        str
    patient_id:      str
    recorded_at:     str       # ISO timestamp
    temperature:     float     # °C
    heart_rate:      int       # BPM
    bp_systolic:     int       # mmHg
    bp_diastolic:    int       # mmHg
    spo2:            float     # %
    respiratory_rate: int      # breaths/min
    recorded_by:     str       # nurse name


@dataclass
class AdmittedPatient:
    patient_id:       str
    name:             str
    age:              int
    ward:             str
    bed_number:       str
    attending_doctor: str
    admitted_at:      str
    diagnosis:        str
    phone:            str = ""
    caregiver_phone:  str = ""


@dataclass
class DeteriorationAlert:
    alert_id:     str
    patient_id:   str
    severity:     str          # low | medium | high | critical
    reasoning:    str          # Agent's full chain-of-thought
    triggered_at: str
    status:       str = "active"   # active | acknowledged | resolved


@dataclass
class AgentMessage:
    message_id:   str
    from_agent:   str
    to_agent:     str
    patient_id:   str
    message_type: str
    content:      str
    sent_at:      str
    processed:    bool = False


# ── Sentinel Store ────────────────────────────────────────────────────────────

class SentinelStore:
    """
    In-memory store for the Deterioration Sentinel Agent.
    Three synthetic patients pre-loaded with distinct patterns:

      CGH-001  Meena K.  — early sepsis signature  (temp↑ HR↑ BP↓)  -> HIGH alert expected
      CGH-002  Ravi S.   — completely stable                          -> no action expected
      CGH-003  Priya N.  — SpO2 slowly declining                     -> MEDIUM alert expected
    """

    def __init__(self):
        now = datetime.now()

        # ── Admitted patients ─────────────────────────────────────────────
        self._patients: Dict[str, AdmittedPatient] = {
            "CGH-001": AdmittedPatient(
                patient_id="CGH-001",
                name="Meena Krishnan",
                age=58,
                ward="Ward 3",
                bed_number="B-14",
                attending_doctor="Dr. R. Sharma",
                admitted_at=(now - timedelta(days=2)).isoformat(timespec="minutes"),
                diagnosis="Post-surgical recovery — abdominal surgery",
                phone="+91-98765-00001",
                caregiver_phone="+91-98765-00002",
            ),
            "CGH-002": AdmittedPatient(
                patient_id="CGH-002",
                name="Ravi Shankar",
                age=45,
                ward="Ward 3",
                bed_number="B-15",
                attending_doctor="Dr. R. Sharma",
                admitted_at=(now - timedelta(days=1)).isoformat(timespec="minutes"),
                diagnosis="Elective knee replacement — Day 1 post-op, scheduled for discharge today",
                phone="+91-98765-00003",
            ),
            "CGH-003": AdmittedPatient(
                patient_id="CGH-003",
                name="Priya Nair",
                age=32,
                ward="ICU",
                bed_number="ICU-2",
                attending_doctor="Dr. P. Mehta",
                admitted_at=(now - timedelta(hours=18)).isoformat(timespec="minutes"),
                diagnosis="Community-acquired pneumonia — on oxygen support",
                phone="+91-98765-00004",
                caregiver_phone="+91-98765-00005",
            ),
        }

        # ── Vitals history ────────────────────────────────────────────────
        # CGH-001 Meena: classic early sepsis — each value alone is normal,
        # but rate of change across 4 readings is the danger signal.
        # Temp: 37.0 -> 37.4 -> 37.8 -> 38.1 (+1.1°C over 12h)
        # HR:   78  -> 85  -> 94  -> 103  (+25 BPM over 12h)
        # BP:   118 -> 112 -> 104 -> 96   (-22 mmHg systolic over 12h)

        # CGH-002 Ravi: boring stable. Agent should say "no action".

        # CGH-003 Priya: SpO2 slowly dropping — respiratory deterioration.
        # 97.0 -> 96.2 -> 95.1 -> 94.0 (-3% over 12h, accelerating)

        self._vitals: List[VitalReading] = [

            # ── Meena (CGH-001) — early sepsis pattern ──────────────────
            VitalReading("V001", "CGH-001", (now - timedelta(hours=12)).isoformat(timespec="minutes"),
                         37.0, 78,  118, 76, 98.5, 16, "Nurse Lakshmi"),
            VitalReading("V002", "CGH-001", (now - timedelta(hours=8)).isoformat(timespec="minutes"),
                         37.4, 85,  112, 72, 97.8, 17, "Nurse Lakshmi"),
            VitalReading("V003", "CGH-001", (now - timedelta(hours=4)).isoformat(timespec="minutes"),
                         37.8, 94,  104, 68, 97.2, 18, "Nurse Preethi"),
            VitalReading("V004", "CGH-001", (now - timedelta(hours=1)).isoformat(timespec="minutes"),
                         38.1, 103, 96,  62, 96.5, 19, "Nurse Preethi"),

            # ── Ravi (CGH-002) — declining into infection ─────────────────────────────────
            VitalReading("V005", "CGH-002", (now - timedelta(hours=12)).isoformat(timespec="minutes"),
                         36.8, 72, 122, 80, 98.8, 15, "Nurse Lakshmi"),
            VitalReading("V006", "CGH-002", (now - timedelta(hours=8)).isoformat(timespec="minutes"),
                         37.1, 78, 115, 75, 98.1, 16, "Nurse Lakshmi"),
            VitalReading("V007", "CGH-002", (now - timedelta(hours=4)).isoformat(timespec="minutes"),
                         37.6, 86, 110, 72, 97.4, 18, "Nurse Preethi"),
            VitalReading("V008", "CGH-002", (now - timedelta(hours=1)).isoformat(timespec="minutes"),
                         38.2, 95, 102, 65, 96.0, 20, "Nurse Preethi"),

            # ── Priya (CGH-003) — SpO2 declining (respiratory concern) ──
            VitalReading("V009", "CGH-003", (now - timedelta(hours=12)).isoformat(timespec="minutes"),
                         37.2, 88, 108, 70, 97.0, 18, "Nurse Kamala"),
            VitalReading("V010", "CGH-003", (now - timedelta(hours=8)).isoformat(timespec="minutes"),
                         37.3, 91, 106, 68, 96.2, 19, "Nurse Kamala"),
            VitalReading("V011", "CGH-003", (now - timedelta(hours=4)).isoformat(timespec="minutes"),
                         37.5, 95, 102, 66, 95.1, 20, "Nurse Kamala"),
            VitalReading("V012", "CGH-003", (now - timedelta(hours=1)).isoformat(timespec="minutes"),
                         37.7, 99, 98,  64, 94.0, 21, "Nurse Kamala"),
        ]

        self._alerts:        List[DeteriorationAlert] = []
        self._messages:      List[AgentMessage]       = []
        self._action_log:    List[dict]               = []

    # ── Patients ──────────────────────────────────────────────────────────

    def get_all_patients(self) -> List[AdmittedPatient]:
        return list(self._patients.values())

    def get_patient(self, patient_id: str) -> Optional[AdmittedPatient]:
        return self._patients.get(patient_id)

    # ── Vitals ────────────────────────────────────────────────────────────

    def get_vitals(self, patient_id: str, last_n: int = 6) -> List[VitalReading]:
        """Return last N vitals for a patient, oldest first."""
        readings = [v for v in self._vitals if v.patient_id == patient_id]
        readings.sort(key=lambda v: v.recorded_at)
        return readings[-last_n:]

    def add_vital(self, reading: VitalReading) -> None:
        self._vitals.append(reading)

    # ── Alerts ────────────────────────────────────────────────────────────

    def get_active_alerts(self, patient_id: str) -> List[DeteriorationAlert]:
        return [a for a in self._alerts if a.patient_id == patient_id and a.status == "active"]

    def create_alert(
        self,
        patient_id: str,
        severity:   str,
        reasoning:  str,
    ) -> DeteriorationAlert:
        alert = DeteriorationAlert(
            alert_id=f"ALRT-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            severity=severity,
            reasoning=reasoning,
            triggered_at=datetime.now().isoformat(timespec="minutes"),
        )
        self._alerts.append(alert)
        self._action_log.append({
            "timestamp":  alert.triggered_at,
            "action":     "create_alert",
            "patient_id": patient_id,
            "severity":   severity,
        })
        return alert

    # ── Inter-agent messages ──────────────────────────────────────────────

    def send_agent_message(
        self,
        to_agent:     str,
        patient_id:   str,
        message_type: str,
        content:      str,
    ) -> AgentMessage:
        msg = AgentMessage(
            message_id=f"MSG-{uuid.uuid4().hex[:6].upper()}",
            from_agent="deterioration_sentinel",
            to_agent=to_agent,
            patient_id=patient_id,
            message_type=message_type,
            content=content,
            sent_at=datetime.now().isoformat(timespec="minutes"),
        )
        self._messages.append(msg)
        self._action_log.append({
            "timestamp":   msg.sent_at,
            "action":      "agent_message",
            "to_agent":    to_agent,
            "patient_id":  patient_id,
            "message_type": message_type,
        })
        return msg

    # ── Audit ─────────────────────────────────────────────────────────────

    def get_alert_log(self)   -> List[DeteriorationAlert]: return self._alerts
    def get_message_log(self) -> List[AgentMessage]:       return self._messages
    def get_action_log(self)  -> List[dict]:               return self._action_log