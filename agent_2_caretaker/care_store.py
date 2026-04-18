"""
care_store.py
=============
In-memory store simulating:
  - Patient care plans (prescribed medications, procedures, vitals schedule)
  - Pharmacy inventory + dispensing log
  - Nurse administration records
  - Pending approvals from doctors
  - Agent action audit log

In production: backed by EMR / hospital DB (Epic, Cerner, etc.)
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import uuid


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class Medication:
    med_id: str
    patient_id: str
    drug_name: str
    dose: str
    route: str                    # oral / IV / IM / topical
    frequency: str                # e.g. "every 8 hours"
    prescribed_at: str            # ISO timestamp
    prescribed_by: str            # doctor ID
    is_critical: bool = False     # antibiotics, anticoagulants, cardiac drugs, etc.
    drug_class: str = ""          # e.g. "beta-lactam antibiotic"
    next_due_at: str = ""
    status: str = "pending"       # pending / dispensed / administered / missed / substituted
    substituted_by: str = ""      # med_id of the substitution, if any


@dataclass
class PharmacyRecord:
    drug_name: str
    in_stock: bool
    stock_count: int
    alternatives: List[str] = field(default_factory=list)   # drug names


@dataclass
class NurseRecord:
    nurse_id: str
    patient_id: str
    med_id: str
    scheduled_at: str
    administered_at: str = ""
    status: str = "scheduled"     # scheduled / administered / missed / rescheduled


@dataclass
class PendingApproval:
    approval_id: str
    patient_id: str
    med_id: str
    approval_type: str            # "drug_substitution" / "escalation"
    description: str
    suggested_action: str
    requested_at: str
    doctor_id: str
    status: str = "pending"       # pending / approved / rejected
    resolved_at: str = ""


@dataclass
class CareGap:
    gap_id: str
    patient_id: str
    gap_type: str                 # "medication_not_dispensed" / "administration_overdue" / "vitals_overdue"
    severity: str                 # "critical" / "moderate" / "low"
    description: str
    detected_at: str
    med_id: str = ""
    resolved: bool = False
    resolution: str = ""


# ── Care Store ───────────────────────────────────────────────────────────────

class CareStore:
    def __init__(self):
        now = datetime.now()
        prescribed_6h_ago = (now - timedelta(hours=6)).isoformat(timespec="minutes")
        prescribed_2h_ago = (now - timedelta(hours=2)).isoformat(timespec="minutes")
        due_now            = now.isoformat(timespec="minutes")
        due_1h_ago         = (now - timedelta(hours=1)).isoformat(timespec="minutes")
        due_3h_ago         = (now - timedelta(hours=3)).isoformat(timespec="minutes")

        # ── Medications ──────────────────────────────────────────────────────
        self._medications: List[Medication] = [
            Medication(
                med_id="MED001",
                patient_id="P001",
                drug_name="Amoxicillin-Clavulanate",
                dose="875mg",
                route="oral",
                frequency="every 12 hours",
                prescribed_at=prescribed_6h_ago,
                prescribed_by="DR001",
                is_critical=True,
                drug_class="beta-lactam antibiotic",
                next_due_at=due_3h_ago,
                status="pending",           # ← never dispensed — THE GAP
            ),
            Medication(
                med_id="MED002",
                patient_id="P001",
                drug_name="Paracetamol",
                dose="500mg",
                route="oral",
                frequency="every 6 hours",
                prescribed_at=prescribed_2h_ago,
                prescribed_by="DR001",
                is_critical=False,
                drug_class="analgesic",
                next_due_at=due_now,
                status="dispensed",
            ),
            Medication(
                med_id="MED003",
                patient_id="P002",
                drug_name="Metoprolol",
                dose="25mg",
                route="oral",
                frequency="every 24 hours",
                prescribed_at=prescribed_6h_ago,
                prescribed_by="DR002",
                is_critical=True,
                drug_class="beta-blocker",
                next_due_at=due_1h_ago,
                status="dispensed",         # dispensed but nurse not confirmed
            ),
        ]

        # ── Pharmacy inventory ───────────────────────────────────────────────
        self._pharmacy: Dict[str, PharmacyRecord] = {
            "Amoxicillin-Clavulanate": PharmacyRecord(
                drug_name="Amoxicillin-Clavulanate",
                in_stock=False,
                stock_count=0,
                alternatives=["Co-Amoxiclav 625mg", "Ampicillin-Sulbactam IV"],
            ),
            "Paracetamol": PharmacyRecord(
                drug_name="Paracetamol", in_stock=True, stock_count=200
            ),
            "Metoprolol": PharmacyRecord(
                drug_name="Metoprolol", in_stock=True, stock_count=50
            ),
            "Co-Amoxiclav 625mg": PharmacyRecord(
                drug_name="Co-Amoxiclav 625mg", in_stock=True, stock_count=30
            ),
            "Ampicillin-Sulbactam IV": PharmacyRecord(
                drug_name="Ampicillin-Sulbactam IV", in_stock=True, stock_count=15
            ),
        }

        # ── Nurse administration records ─────────────────────────────────────
        self._nurse_records: List[NurseRecord] = [
            NurseRecord(
                nurse_id="N001",
                patient_id="P001",
                med_id="MED001",
                scheduled_at=due_3h_ago,
                status="scheduled",   # overdue — no administration confirmed
            ),
            NurseRecord(
                nurse_id="N001",
                patient_id="P002",
                med_id="MED003",
                scheduled_at=due_1h_ago,
                status="scheduled",   # dispensed but nurse not confirmed
            ),
        ]

        # ── Patients (lightweight for care context) ──────────────────────────
        self._patients: Dict[str, dict] = {
            "P001": {"name": "Meena P.", "age": 70, "ward": "Cardiology-3B", "doctor_id": "DR001", "diagnosis": "Community-acquired pneumonia, post-MI"},
            "P002": {"name": "Arjun K.", "age": 45, "ward": "General-2A",    "doctor_id": "DR002", "diagnosis": "Hypertensive crisis, fever"},
        }

        # ── Doctors ──────────────────────────────────────────────────────────
        self._doctors: Dict[str, dict] = {
            "DR001": {"name": "Dr. Priya Nair",    "phone": "+91-98001-11111", "speciality": "Cardiology"},
            "DR002": {"name": "Dr. Ramesh Kumar",  "phone": "+91-98001-22222", "speciality": "Internal Medicine"},
        }

        self._pending_approvals: List[PendingApproval] = []
        self._care_gaps: List[CareGap] = []
        self._action_log: List[dict] = []
        self._sms_log: List[dict] = []

    # ── Medications ─────────────────────────────────────────────────────────

    def get_all_medications(self) -> List[Medication]:
        return self._medications

    def get_medication(self, med_id: str) -> Optional[Medication]:
        return next((m for m in self._medications if m.med_id == med_id), None)

    def update_medication_status(self, med_id: str, status: str, substituted_by: str = "") -> bool:
        med = self.get_medication(med_id)
        if not med:
            return False
        med.status = status
        med.substituted_by = substituted_by
        return True

    def add_medication(self, med: Medication) -> None:
        self._medications.append(med)

    # ── Pharmacy ─────────────────────────────────────────────────────────────

    def query_pharmacy(self, drug_name: str) -> Optional[PharmacyRecord]:
        return self._pharmacy.get(drug_name)

    def all_pharmacy_records(self) -> Dict[str, PharmacyRecord]:
        return self._pharmacy

    # ── Nurse records ────────────────────────────────────────────────────────

    def get_nurse_record(self, med_id: str) -> Optional[NurseRecord]:
        return next((r for r in self._nurse_records if r.med_id == med_id), None)

    def update_nurse_record(self, med_id: str, status: str, new_scheduled_at: str = "") -> bool:
        rec = self.get_nurse_record(med_id)
        if not rec:
            return False
        rec.status = status
        if new_scheduled_at:
            rec.scheduled_at = new_scheduled_at
        return True

    def add_nurse_record(self, rec: NurseRecord) -> None:
        self._nurse_records.append(rec)

    # ── Patients ─────────────────────────────────────────────────────────────

    def get_patient(self, patient_id: str) -> Optional[dict]:
        return self._patients.get(patient_id)

    def get_doctor(self, doctor_id: str) -> Optional[dict]:
        return self._doctors.get(doctor_id)

    # ── Pending approvals ────────────────────────────────────────────────────

    def create_approval_request(
        self, patient_id: str, med_id: str, approval_type: str,
        description: str, suggested_action: str, doctor_id: str
    ) -> PendingApproval:
        appr = PendingApproval(
            approval_id=f"APPR-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            med_id=med_id,
            approval_type=approval_type,
            description=description,
            suggested_action=suggested_action,
            requested_at=datetime.now().isoformat(timespec="minutes"),
            doctor_id=doctor_id,
        )
        self._pending_approvals.append(appr)
        return appr

    def approve(self, approval_id: str) -> bool:
        appr = next((a for a in self._pending_approvals if a.approval_id == approval_id), None)
        if not appr:
            return False
        appr.status = "approved"
        appr.resolved_at = datetime.now().isoformat(timespec="minutes")
        return True

    def get_pending_approvals(self) -> List[PendingApproval]:
        return [a for a in self._pending_approvals if a.status == "pending"]

    # ── Care gaps ────────────────────────────────────────────────────────────

    def record_gap(self, patient_id: str, gap_type: str, severity: str,
                   description: str, med_id: str = "") -> CareGap:
        gap = CareGap(
            gap_id=f"GAP-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            gap_type=gap_type,
            severity=severity,
            description=description,
            detected_at=datetime.now().isoformat(timespec="minutes"),
            med_id=med_id,
        )
        self._care_gaps.append(gap)
        return gap

    def resolve_gap(self, gap_id: str, resolution: str) -> bool:
        gap = next((g for g in self._care_gaps if g.gap_id == gap_id), None)
        if not gap:
            return False
        gap.resolved = True
        gap.resolution = resolution
        return True

    def get_open_gaps(self) -> List[CareGap]:
        return [g for g in self._care_gaps if not g.resolved]

    # ── Logs ────────────────────────────────────────────────────────────────

    def log_action(self, action_type: str, detail: dict) -> None:
        self._action_log.append({
            "timestamp": datetime.now().isoformat(timespec="minutes"),
            "action_type": action_type,
            "detail": detail,
        })

    def log_sms(self, recipient: str, phone: str, message: str) -> None:
        self._sms_log.append({
            "timestamp": datetime.now().isoformat(timespec="minutes"),
            "recipient": recipient,
            "phone": phone,
            "message": message,
        })

    def get_action_log(self) -> List[dict]:
        return self._action_log

    def get_sms_log(self) -> List[dict]:
        return self._sms_log