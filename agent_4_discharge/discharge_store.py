"""
discharge_store.py
==================
In-memory store for the Discharge Negotiator Agent.
Mirrors the style of PatientStore (agent_1), CareStore (agent_2), SentinelStore (agent_3).

Simulates:
  - Admitted patients with clinical readiness status
  - Discharge blockers (summary, insurance, pharmacy, transport)
  - Insurance pre-auth records
  - Discharge summaries
  - Inter-agent message bus
  - SMS / family notification log
  - Audit log

In production: backed by PostgreSQL / hospital EMR (Epic, Cerner).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import uuid


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class DischargePatient:
    patient_id:          str
    name:                str
    age:                 int
    ward:                str
    bed_number:          str
    attending_doctor:    str
    doctor_id:           str
    admitted_at:         str
    diagnosis:           str
    icd10_codes:         List[str]
    phone:               str = ""
    family_phone:        str = ""
    insurance_id:        str = ""
    insurance_provider:  str = ""
    vitals_stable_since: str = ""      # ISO — how long vitals have been normal
    clinically_ready:    bool = False  # attending doctor has cleared discharge
    discharge_eta:       str = ""      # estimated discharge time (ISO)


@dataclass
class DischargeBlocker:
    blocker_id:   str
    patient_id:   str
    blocker_type: str     # summary | insurance | pharmacy | transport
    description:  str
    status:       str     # pending | in_progress | resolved
    detected_at:  str
    priority:     str = "medium"   # low | medium | high
    resolved_at:  str = ""
    resolution:   str = ""


@dataclass
class InsurancePreAuth:
    auth_id:          str
    patient_id:       str
    provider:         str
    icd10_codes:      List[str]
    submitted_at:     str
    status:           str = "not_submitted"   # not_submitted | submitted | approved | rejected
    auth_number:      str = ""
    approved_at:      str = ""
    rejection_reason: str = ""


@dataclass
class DischargeSummary:
    summary_id: str
    patient_id: str
    content:    str
    drafted_at: str
    status:     str = "draft"   # draft | sent_to_doctor | signed


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


# ── Discharge Store ───────────────────────────────────────────────────────────

class DischargeStore:
    """
    Three synthetic patients pre-loaded:

      DIS-001  Ravi Shankar, 45M   — clinically ready, 4 blockers
               (summary not written, insurance not submitted,
                pharmacy has 2 pending, transport not arranged)
               -> Agent should resolve all 4, set ETA, SMS patient + family

      DIS-002  Priya Nair, 32F    — NOT clinically ready (vitals only stable 2h)
               -> Agent should detect NOT ready, skip, log reason

      DIS-003  Meena Krishnan, 58F — ready, 1 blocker (transport only)
               -> Agent should resolve transport, confirm discharge time
    """

    def __init__(self):
        now         = datetime.now()
        stable_48h  = (now - timedelta(hours=48)).isoformat(timespec="minutes")
        stable_2h   = (now - timedelta(hours=2)).isoformat(timespec="minutes")
        admitted_3d = (now - timedelta(days=3)).isoformat(timespec="minutes")
        admitted_1d = (now - timedelta(days=1)).isoformat(timespec="minutes")
        admitted_5d = (now - timedelta(days=5)).isoformat(timespec="minutes")
        eta_ravi    = (now + timedelta(hours=3)).strftime("%I:%M %p")
        eta_meena   = (now + timedelta(hours=1)).strftime("%I:%M %p")

        # ── Patients ─────────────────────────────────────────────────────
        self._patients: Dict[str, DischargePatient] = {
            "DIS-001": DischargePatient(
                patient_id="DIS-001",
                name="Ravi Shankar",
                age=45,
                ward="Ward 3",
                bed_number="B-15",
                attending_doctor="Dr. R. Sharma",
                doctor_id="DR001",
                admitted_at=admitted_3d,
                diagnosis="Elective knee replacement — Day 3 post-op. "
                          "Full ROM achieved. No fever. Wound clean.",
                icd10_codes=["M17.11", "Z96.641"],
                phone="+91-98765-00003",
                family_phone="+91-98765-00099",
                insurance_id="INS-RVS-4421",
                insurance_provider="Star Health Insurance",
                vitals_stable_since=stable_48h,
                clinically_ready=True,
                discharge_eta="",
            ),
            "DIS-002": DischargePatient(
                patient_id="DIS-002",
                name="Priya Nair",
                age=32,
                ward="ICU",
                bed_number="ICU-2",
                attending_doctor="Dr. P. Mehta",
                doctor_id="DR002",
                admitted_at=admitted_1d,
                diagnosis="Community-acquired pneumonia — still on 2L O2 support. "
                          "SpO2 trending down. Not medically cleared.",
                icd10_codes=["J18.9"],
                phone="+91-98765-00004",
                family_phone="+91-98765-00005",
                insurance_id="INS-PRN-8812",
                insurance_provider="HDFC Ergo Health",
                vitals_stable_since=stable_2h,
                clinically_ready=False,
                discharge_eta="",
            ),
            "DIS-003": DischargePatient(
                patient_id="DIS-003",
                name="Meena Krishnan",
                age=58,
                ward="Ward 2",
                bed_number="A-08",
                attending_doctor="Dr. R. Sharma",
                doctor_id="DR001",
                admitted_at=admitted_5d,
                diagnosis="Post-CABG recovery — Day 5. Cleared by cardiology. "
                          "Vitals stable 48h. Medications dispensed. "
                          "Insurance pre-auth already approved.",
                icd10_codes=["I25.10", "Z95.1"],
                phone="+91-98765-00001",
                family_phone="+91-98765-00002",
                insurance_id="INS-MEK-5531",
                insurance_provider="New India Assurance",
                vitals_stable_since=stable_48h,
                clinically_ready=True,
                discharge_eta="",
            ),
        }

        # ── Discharge blockers ────────────────────────────────────────────
        self._blockers: List[DischargeBlocker] = [
            # ── Ravi: 4 blockers ─────────────────────────────────────────
            DischargeBlocker(
                blocker_id="BLK-001", patient_id="DIS-001",
                blocker_type="summary",
                description="Discharge summary not written. Required before patient leaves.",
                status="pending", priority="high",
                detected_at=now.isoformat(timespec="minutes"),
            ),
            DischargeBlocker(
                blocker_id="BLK-002", patient_id="DIS-001",
                blocker_type="insurance",
                description="Insurance pre-authorisation not submitted to Star Health Insurance "
                            "(ICD-10: M17.11, Z96.641). Required for cashless discharge.",
                status="pending", priority="high",
                detected_at=now.isoformat(timespec="minutes"),
            ),
            DischargeBlocker(
                blocker_id="BLK-003", patient_id="DIS-001",
                blocker_type="pharmacy",
                description="2 take-home medications pending: "
                            "Pantoprazole 40mg (14-day supply) and "
                            "Enoxaparin 40mg injection (7-day supply).",
                status="pending", priority="medium",
                detected_at=now.isoformat(timespec="minutes"),
            ),
            DischargeBlocker(
                blocker_id="BLK-004", patient_id="DIS-001",
                blocker_type="transport",
                description="Transport not arranged. Family not contacted about pickup.",
                status="pending", priority="medium",
                detected_at=now.isoformat(timespec="minutes"),
            ),
            # ── Meena: 1 blocker ─────────────────────────────────────────
            DischargeBlocker(
                blocker_id="BLK-005", patient_id="DIS-003",
                blocker_type="transport",
                description="Transport not arranged. Family has not confirmed pickup time.",
                status="pending", priority="medium",
                detected_at=now.isoformat(timespec="minutes"),
            ),
        ]

        # ── Insurance pre-auth records ────────────────────────────────────
        self._preauths: List[InsurancePreAuth] = [
            InsurancePreAuth(
                auth_id="AUTH-001", patient_id="DIS-001",
                provider="Star Health Insurance",
                icd10_codes=["M17.11", "Z96.641"],
                submitted_at="", status="not_submitted",
            ),
            InsurancePreAuth(
                auth_id="AUTH-003", patient_id="DIS-003",
                provider="New India Assurance",
                icd10_codes=["I25.10", "Z95.1"],
                submitted_at=(now - timedelta(hours=3)).isoformat(timespec="minutes"),
                status="approved",
                auth_number="NIA-2026-88821",
                approved_at=(now - timedelta(hours=2)).isoformat(timespec="minutes"),
            ),
        ]

        # ── Discharge summaries ───────────────────────────────────────────
        self._summaries: List[DischargeSummary] = []

        # ── Doctors ──────────────────────────────────────────────────────
        self._doctors: Dict[str, dict] = {
            "DR001": {"name": "Dr. R. Sharma", "phone": "+91-98001-11111", "speciality": "Orthopaedics"},
            "DR002": {"name": "Dr. P. Mehta",  "phone": "+91-98001-22222", "speciality": "Pulmonology"},
        }

        self._agent_messages: List[AgentMessage] = []
        self._sms_log:        List[dict]          = []
        self._action_log:     List[dict]          = []

    # ── Patients ──────────────────────────────────────────────────────────

    def get_all_patients(self) -> List[DischargePatient]:
        return list(self._patients.values())

    def get_patient(self, patient_id: str) -> Optional[DischargePatient]:
        return self._patients.get(patient_id)

    def get_doctor(self, doctor_id: str) -> Optional[dict]:
        return self._doctors.get(doctor_id)

    def update_discharge_eta(self, patient_id: str, eta: str) -> bool:
        p = self._patients.get(patient_id)
        if not p:
            return False
        p.discharge_eta = eta
        self._action_log.append({
            "timestamp": datetime.now().isoformat(timespec="minutes"),
            "action": "update_eta",
            "patient_id": patient_id,
            "eta": eta,
        })
        return True

    # ── Blockers ──────────────────────────────────────────────────────────

    def get_blockers(self, patient_id: str) -> List[DischargeBlocker]:
        return [b for b in self._blockers if b.patient_id == patient_id]

    def get_open_blockers(self, patient_id: str) -> List[DischargeBlocker]:
        return [b for b in self._blockers if b.patient_id == patient_id and b.status != "resolved"]

    def resolve_blocker(self, blocker_id: str, resolution: str) -> bool:
        b = next((x for x in self._blockers if x.blocker_id == blocker_id), None)
        if not b:
            return False
        b.status = "resolved"
        b.resolved_at = datetime.now().isoformat(timespec="minutes")
        b.resolution = resolution
        self._action_log.append({
            "timestamp":   datetime.now().isoformat(timespec="minutes"),
            "action":      "resolve_blocker",
            "blocker_id":  blocker_id,
            "blocker_type": b.blocker_type,
            "patient_id":  b.patient_id,
            "resolution":  resolution,
        })
        return True

    def update_blocker_status(self, blocker_id: str, status: str) -> bool:
        b = next((x for x in self._blockers if x.blocker_id == blocker_id), None)
        if not b:
            return False
        b.status = status
        return True

    # ── Insurance ─────────────────────────────────────────────────────────

    def get_preauth(self, patient_id: str) -> Optional[InsurancePreAuth]:
        return next((a for a in self._preauths if a.patient_id == patient_id), None)

    def submit_preauth(self, patient_id: str) -> InsurancePreAuth:
        auth = self.get_preauth(patient_id)
        if not auth:
            p = self._patients[patient_id]
            auth = InsurancePreAuth(
                auth_id=f"AUTH-{uuid.uuid4().hex[:6].upper()}",
                patient_id=patient_id,
                provider=p.insurance_provider,
                icd10_codes=p.icd10_codes,
                submitted_at="",
            )
            self._preauths.append(auth)
        auth.submitted_at = datetime.now().isoformat(timespec="minutes")
        auth.status       = "approved"   # simulated auto-approval
        auth.auth_number  = f"PRE-{uuid.uuid4().hex[:8].upper()}"
        auth.approved_at  = datetime.now().isoformat(timespec="minutes")
        self._action_log.append({
            "timestamp":   datetime.now().isoformat(timespec="minutes"),
            "action":      "submit_preauth",
            "patient_id":  patient_id,
            "auth_number": auth.auth_number,
        })
        return auth

    # ── Discharge summaries ───────────────────────────────────────────────

    def create_summary(self, patient_id: str, content: str) -> DischargeSummary:
        s = DischargeSummary(
            summary_id=f"SUM-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            content=content,
            drafted_at=datetime.now().isoformat(timespec="minutes"),
        )
        self._summaries.append(s)
        self._action_log.append({
            "timestamp":  datetime.now().isoformat(timespec="minutes"),
            "action":     "create_summary",
            "patient_id": patient_id,
            "summary_id": s.summary_id,
        })
        return s

    def get_summary(self, patient_id: str) -> Optional[DischargeSummary]:
        return next((s for s in self._summaries if s.patient_id == patient_id), None)

    # ── Agent messages ────────────────────────────────────────────────────

    def send_agent_message(self, to_agent: str, patient_id: str,
                           message_type: str, content: str) -> AgentMessage:
        msg = AgentMessage(
            message_id=f"MSG-{uuid.uuid4().hex[:6].upper()}",
            from_agent="discharge_negotiator",
            to_agent=to_agent,
            patient_id=patient_id,
            message_type=message_type,
            content=content,
            sent_at=datetime.now().isoformat(timespec="minutes"),
        )
        self._agent_messages.append(msg)
        self._action_log.append({
            "timestamp":    datetime.now().isoformat(timespec="minutes"),
            "action":       "agent_message",
            "to_agent":     to_agent,
            "patient_id":   patient_id,
            "message_type": message_type,
        })
        return msg

    # ── SMS ───────────────────────────────────────────────────────────────

    def log_sms(self, recipient: str, phone: str, message: str) -> None:
        self._sms_log.append({
            "timestamp": datetime.now().isoformat(timespec="minutes"),
            "recipient": recipient,
            "phone":     phone,
            "message":   message,
        })

    # ── Audit ─────────────────────────────────────────────────────────────

    def get_action_log(self)      -> List[dict]:          return self._action_log
    def get_sms_log(self)         -> List[dict]:          return self._sms_log
    def get_agent_messages(self)  -> List[AgentMessage]:  return self._agent_messages