"""
Shared operational state for HospitalOS workflows.

This module provides a single in-memory workflow state store that all agents
can read from and write to. It is the shared memory layer that keeps patient
workflows alive across agent cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import threading
import uuid


WORKFLOW_STATES = [
    "ADMITTED",
    "TRIAGE_PENDING",
    "TRIAGE_COMPLETE",
    "UNDER_MONITORING",
    "DETERIORATION_REVIEW",
    "MEDICATION_PENDING",
    "PHARMACY_REVIEW",
    "DOCTOR_APPROVAL_PENDING",
    "DISCHARGE_PENDING",
    "DISCHARGE_BLOCKED",
    "DISCHARGED",
    "RECOVERY_MONITORING",
    "PRESCRIPTION_ACTIVE",
    "PRESCRIPTION_COMPLETED",
    "RECOVERED",
]


@dataclass
class PatientWorkflowState:
    patient_id: str
    name: str
    workflow_state: str = "ADMITTED"
    previous_state: str = ""
    state_changed_at: str = ""

    active_alert_ids: List[str] = field(default_factory=list)
    discharge_hold: bool = False
    discharge_hold_reason: str = ""

    assigned_staff: List[str] = field(default_factory=list)
    pending_tasks: List[str] = field(default_factory=list)
    pending_approval_ids: List[str] = field(default_factory=list)

    family_notified: bool = False
    family_notified_at: str = ""
    last_sms_to_patient: str = ""

    medication_status: Dict[str, str] = field(default_factory=dict)

    workflow_id: str = ""
    correlation_ids: List[str] = field(default_factory=list)

    def transition_to(self, new_state: str, reason: str = "") -> None:
        if new_state not in WORKFLOW_STATES:
            raise ValueError(f"Unknown workflow state: {new_state}")
        self.previous_state = self.workflow_state
        self.workflow_state = new_state
        self.state_changed_at = datetime.now().isoformat(timespec="seconds")
        if reason:
            self.correlation_ids.append(reason)

    def to_dict(self) -> dict:
        return asdict(self)


class OperationalEvent:
    """Compact machine-readable event emitter for workflow actions."""

    @staticmethod
    def emit(
        event: str,
        agent: str,
        patient_id: str,
        priority: str = "info",
        next_action: str = "",
        workflow_state: str = "",
        detail: Optional[dict] = None,
    ) -> dict:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "agent": agent,
            "patient_id": patient_id,
            "priority": priority,
            "next_action": next_action,
            "workflow_state": workflow_state,
        }
        if detail:
            record.update(detail)
        print(f"  [{priority.upper()}] {agent} | {event} | {patient_id} -> {next_action}")
        return record


class OperationalStateStore:
    """Singleton workflow state store for all agents."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._states: Dict[str, PatientWorkflowState] = {}
                inst._transition_log: List[dict] = []
                cls._instance = inst
        return cls._instance

    def get(self, patient_id: str) -> Optional[PatientWorkflowState]:
        return self._states.get(patient_id)

    def get_or_create(self, patient_id: str, name: str = "") -> PatientWorkflowState:
        if patient_id not in self._states:
            state = PatientWorkflowState(
                patient_id=patient_id,
                name=name,
                workflow_id=str(uuid.uuid4()),
                state_changed_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._states[patient_id] = state
        elif name and not self._states[patient_id].name:
            self._states[patient_id].name = name
        return self._states[patient_id]

    def transition(self, patient_id: str, new_state: str, reason: str = "", agent: str = "") -> PatientWorkflowState:
        state = self.get_or_create(patient_id)
        old_state = state.workflow_state
        state.transition_to(new_state, reason)
        self._transition_log.append({
            "timestamp": state.state_changed_at,
            "patient_id": patient_id,
            "from_state": old_state,
            "to_state": new_state,
            "reason": reason,
            "agent": agent,
        })
        return state

    def set_discharge_hold(self, patient_id: str, hold: bool, reason: str = "") -> None:
        state = self.get_or_create(patient_id)
        state.discharge_hold = hold
        state.discharge_hold_reason = reason

    def add_alert(self, patient_id: str, alert_id: str) -> None:
        state = self.get_or_create(patient_id)
        if alert_id not in state.active_alert_ids:
            state.active_alert_ids.append(alert_id)

    def update_medication(self, patient_id: str, med_id: str, status: str) -> None:
        state = self.get_or_create(patient_id)
        state.medication_status[med_id] = status

    def add_task(self, patient_id: str, task: str) -> None:
        state = self.get_or_create(patient_id)
        if task not in state.pending_tasks:
            state.pending_tasks.append(task)

    def all_states(self) -> List[PatientWorkflowState]:
        return list(self._states.values())

    def get_transition_log(self) -> List[dict]:
        return list(self._transition_log)


ops = OperationalStateStore()