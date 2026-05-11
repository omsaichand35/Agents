"""
shared_bus.py
=============
PatientOS Shared Message Bus
==============================
Singleton in-process message bus used by ALL agents.

In production: swap the in-memory dict for Redis Pub/Sub or RabbitMQ.
The public API is identical — every agent calls the same three functions.

Usage (any agent):
    from shared_bus import bus

    # Send a message to another agent
    bus.publish(
        from_agent   = "deterioration_sentinel",
        to_agent     = "discharge_negotiator",
        patient_id   = "CGH-001",
        message_type = "hold_discharge",
        content      = "Patient showing early sepsis pattern. Do not discharge.",
        priority     = "high",
    )

    # Read messages addressed to this agent
    messages = bus.get_inbox("discharge_negotiator")

    # Mark a message processed after handling it
    bus.mark_processed(message_id)

Supported message types (enforced):
    hold_discharge          sentinel  -> discharge
    discharge_cleared       discharge -> sentinel / care
    patient_discharged      discharge -> sentinel / triage / recovery
    bed_available           discharge -> triage
    check_medication_gaps   sentinel  -> care
    high_acuity_alert       triage    -> care / sentinel
    medication_gap_found    care      -> sentinel / triage
    fyi_deterioration       sentinel  -> care / triage
    recovery_escalation     recovery  -> care / triage
    patient_recovered       recovery  -> triage
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Dict
from datetime import datetime
import uuid
import threading


# ── Message model ─────────────────────────────────────────────────────────

VALID_AGENTS = {
    "triage_orchestrator",
    "care_continuity",
    "deterioration_sentinel",
    "discharge_negotiator",
    "recovery_guardian",
}

VALID_MESSAGE_TYPES = {
    "hold_discharge",
    "discharge_cleared",
    "patient_discharged",
    "bed_available",
    "check_medication_gaps",
    "high_acuity_alert",
    "medication_gap_found",
    "fyi_deterioration",
    "recovery_escalation",
    "patient_recovered",
    "fyi",                    # generic informational — use sparingly
}

PRIORITY_LEVELS = {"low", "medium", "high", "critical"}


@dataclass
class BusMessage:
    message_id:   str
    from_agent:   str
    to_agent:     str
    patient_id:   str
    message_type: str
    content:      str
    priority:     str
    sent_at:      str
    processed:    bool = False
    processed_at: str  = ""
    response:     str  = ""   # optional reply written back by consumer


# ── Singleton bus ─────────────────────────────────────────────────────────

class MessageBus:
    """
    Thread-safe in-memory message bus.
    All agents share a single instance via `bus` at module level.
    """

    _instance: Optional["MessageBus"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "MessageBus":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._messages = []
                inst._subscribers = {a: [] for a in VALID_AGENTS}
                inst._subscriptions = []
                inst._audit_log = []
                cls._instance = inst
        return cls._instance

    # ── Subscribe ───────────────────────────────────────────────────────

    def subscribe(
        self,
        agent: str,
        message_types: List[str],
        handler: Callable[[BusMessage], None],
        workflow_state_filter: Optional[str] = None,
    ) -> str:
        """Register a synchronous callback for matching published messages."""
        if agent not in VALID_AGENTS:
            raise ValueError(f"Unknown agent: {agent}")
        if not message_types:
            raise ValueError("message_types must not be empty")

        sub_id = f"SUB-{uuid.uuid4().hex[:6].upper()}"
        with self._lock:
            self._subscriptions.append({
                "sub_id": sub_id,
                "agent": agent,
                "message_types": set(message_types),
                "handler": handler,
                "workflow_state_filter": workflow_state_filter,
            })
        return sub_id

    # ── Publish ───────────────────────────────────────────────────────────

    def publish(
        self,
        from_agent:   str,
        to_agent:     str,
        patient_id:   str,
        message_type: str,
        content:      str,
        priority:     str = "medium",
    ) -> BusMessage:
        if from_agent not in VALID_AGENTS:
            raise ValueError(f"Unknown from_agent: {from_agent}")
        if to_agent not in VALID_AGENTS:
            raise ValueError(f"Unknown to_agent: {to_agent}")
        if message_type not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Unknown message_type: {message_type}")
        if priority not in PRIORITY_LEVELS:
            raise ValueError(f"Unknown priority: {priority}")

        msg = BusMessage(
            message_id   = f"BUS-{uuid.uuid4().hex[:8].upper()}",
            from_agent   = from_agent,
            to_agent     = to_agent,
            patient_id   = patient_id,
            message_type = message_type,
            content      = content,
            priority     = priority,
            sent_at      = datetime.now().isoformat(timespec="seconds"),
        )
        subscriptions_to_fire: List[dict] = []
        with self._lock:
            self._messages.append(msg)
            self._audit_log.append({
                "timestamp":    msg.sent_at,
                "event":        "published",
                "message_id":   msg.message_id,
                "from_agent":   from_agent,
                "to_agent":     to_agent,
                "patient_id":   patient_id,
                "message_type": message_type,
                "priority":     priority,
            })
            for sub in self._subscriptions:
                if sub["agent"] != to_agent:
                    continue
                if message_type not in sub["message_types"]:
                    continue
                state_filter = sub.get("workflow_state_filter")
                if state_filter:
                    try:
                        from shared_state import ops

                        state = ops.get(patient_id)
                        if not state or state.workflow_state != state_filter:
                            continue
                    except Exception:
                        continue
                subscriptions_to_fire.append(sub)
        print(
            f"  [BUS > {from_agent} -> {to_agent}] "
            f"[{priority.upper()}] {message_type} | patient={patient_id} | {content[:80]}"
        )
        for sub in subscriptions_to_fire:
            try:
                sub["handler"](msg)
            except Exception as exc:
                self._audit_log.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "subscription_error",
                    "message_id": msg.message_id,
                    "subscription_id": sub["sub_id"],
                    "agent": sub["agent"],
                    "error": str(exc),
                })
                print(f"  [BUS subscription error] {sub['agent']} -> {exc}")
        return msg

    # ── Consume ───────────────────────────────────────────────────────────

    def get_inbox(
        self,
        agent:       str,
        unread_only: bool = True,
        patient_id:  Optional[str] = None,
    ) -> List[BusMessage]:
        """Return messages addressed to `agent`, newest first."""
        with self._lock:
            msgs = [
                m for m in self._messages
                if m.to_agent == agent
                and (not unread_only or not m.processed)
                and (patient_id is None or m.patient_id == patient_id)
            ]
        return sorted(msgs, key=lambda m: m.sent_at, reverse=True)

    def mark_processed(self, message_id: str, response: str = "") -> bool:
        with self._lock:
            for m in self._messages:
                if m.message_id == message_id:
                    m.processed    = True
                    m.processed_at = datetime.now().isoformat(timespec="seconds")
                    m.response     = response
                    self._audit_log.append({
                        "timestamp":  m.processed_at,
                        "event":      "processed",
                        "message_id": message_id,
                        "to_agent":   m.to_agent,
                        "response":   response[:120],
                    })
                    return True
        return False

    # ── Inspect ───────────────────────────────────────────────────────────

    def get_all_messages(self) -> List[BusMessage]:
        with self._lock:
            return list(self._messages)

    def get_audit_log(self) -> List[dict]:
        with self._lock:
            return list(self._audit_log)

    def summary(self) -> dict:
        with self._lock:
            total     = len(self._messages)
            unread    = sum(1 for m in self._messages if not m.processed)
            by_type   = {}
            by_agent  = {}
            for m in self._messages:
                by_type[m.message_type]  = by_type.get(m.message_type, 0) + 1
                by_agent[m.from_agent]   = by_agent.get(m.from_agent, 0) + 1
        return {
            "total_messages": total,
            "unread_messages": unread,
            "by_message_type": by_type,
            "by_sending_agent": by_agent,
        }


# ── Module-level singleton — import this everywhere ───────────────────────
bus = MessageBus()