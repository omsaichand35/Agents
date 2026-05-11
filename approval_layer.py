"""
Human approval layer for HospitalOS workflows.

This module tracks approval requests that need clinician or staff review.
For demo purposes, requests can be auto-approved, but the state remains
visible and auditable so the workflow can later be switched to manual review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
import threading
import uuid


@dataclass
class ApprovalRequest:
    approval_id: str
    patient_id: str
    agent: str
    action_type: str
    description: str
    suggested_action: str
    requested_at: str
    status: str = "pending"
    resolved_at: str = ""
    resolved_by: str = ""
    timeout_seconds: int = 300

    def is_timed_out(self) -> bool:
        if self.status != "pending":
            return False
        elapsed = (datetime.now() - datetime.fromisoformat(self.requested_at)).total_seconds()
        return elapsed > self.timeout_seconds


class ApprovalLayer:
    """Singleton store for approval requests."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._requests: Dict[str, ApprovalRequest] = {}
                cls._instance = inst
        return cls._instance

    def request(
        self,
        patient_id: str,
        agent: str,
        action_type: str,
        description: str,
        suggested_action: str,
        auto_approve: bool = True,
    ) -> ApprovalRequest:
        approval = ApprovalRequest(
            approval_id=f"APPR-{uuid.uuid4().hex[:6].upper()}",
            patient_id=patient_id,
            agent=agent,
            action_type=action_type,
            description=description,
            suggested_action=suggested_action,
            requested_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._requests[approval.approval_id] = approval

        if auto_approve:
            approval.status = "approved"
            approval.resolved_at = datetime.now().isoformat(timespec="seconds")
            approval.resolved_by = "auto_simulated"
            print(
                f"  [APPROVAL] {action_type} | {patient_id} | "
                f"{suggested_action[:60]} -> approved (simulated)"
            )
        else:
            print(f"  [APPROVAL] {action_type} | {patient_id} -> pending human review")

        return approval

    def approve(self, approval_id: str, resolved_by: str = "human") -> bool:
        approval = self._requests.get(approval_id)
        if not approval or approval.status != "pending":
            return False
        approval.status = "approved"
        approval.resolved_at = datetime.now().isoformat(timespec="seconds")
        approval.resolved_by = resolved_by
        return True

    def reject(self, approval_id: str, resolved_by: str = "human") -> bool:
        approval = self._requests.get(approval_id)
        if not approval or approval.status != "pending":
            return False
        approval.status = "rejected"
        approval.resolved_at = datetime.now().isoformat(timespec="seconds")
        approval.resolved_by = resolved_by
        return True

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._requests.get(approval_id)

    def get_pending(self) -> List[ApprovalRequest]:
        return [approval for approval in self._requests.values() if approval.status == "pending"]

    def get_timed_out(self) -> List[ApprovalRequest]:
        return [approval for approval in self._requests.values() if approval.is_timed_out()]

    def all_requests(self) -> List[ApprovalRequest]:
        return list(self._requests.values())


approvals = ApprovalLayer()