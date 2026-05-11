"""
Canonical patient identity registry.

This module provides a shared mapping between the single canonical patient ID
used by the workflow and the local IDs used inside each agent-specific store.
"""

from __future__ import annotations

from typing import Dict, Optional


PATIENT_REGISTRY: Dict[str, Dict[str, str]] = {
    "P-RAVI-001": {
        "name": "Ravi Shankar",
        "triage_id": "P001",
        "care_id": "P002",
        "sentinel_id": "CGH-002",
        "discharge_id": "DIS-001",
        "recovery_id": "REC-002",
    },
    "P-MEENA-001": {
        "name": "Meena Krishnan",
        "triage_id": "P002",
        "care_id": "P001",
        "sentinel_id": "CGH-001",
        "discharge_id": "DIS-003",
        "recovery_id": "REC-001",
    },
    "P-ARJUN-001": {
        "name": "Arjun K.",
        "triage_id": "P003",
        "care_id": "P002",
        "sentinel_id": "",
        "discharge_id": "",
        "recovery_id": "REC-003",
    },
    "P-PRIYA-001": {
        "name": "Priya Nair",
        "triage_id": "P004",
        "care_id": "",
        "sentinel_id": "CGH-003",
        "discharge_id": "DIS-002",
        "recovery_id": "",
    },
}


def get_patient_record(canonical_id: str) -> Optional[Dict[str, str]]:
    """Return the registry entry for a canonical patient ID."""
    return PATIENT_REGISTRY.get(canonical_id)


def get_canonical_patient_id(agent_id: str, local_patient_id: str) -> Optional[str]:
    """Return the canonical ID for a local agent-specific patient ID."""
    for canonical_id, entry in PATIENT_REGISTRY.items():
        if entry.get(agent_id) == local_patient_id:
            return canonical_id
    return None


def get_local_patient_id(canonical_id: str, agent_id: str) -> Optional[str]:
    """Return the agent-local patient ID for a canonical ID."""
    entry = PATIENT_REGISTRY.get(canonical_id)
    if not entry:
        return None
    local_id = entry.get(agent_id, "")
    return local_id or None


def get_canonical_name(canonical_id: str) -> Optional[str]:
    """Return the canonical display name for a patient."""
    entry = PATIENT_REGISTRY.get(canonical_id)
    if not entry:
        return None
    return entry.get("name")