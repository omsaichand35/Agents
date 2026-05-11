"""
demo.py
=======
Runs a single triage cycle immediately — no 5-minute sleep.
Useful for testing / CI without modifying the main agent.

Usage:
    python demo.py

Set ANTHROPIC_API_KEY in your environment first.
"""

import os
from google import genai
from patient_store import PatientStore, Patient
from triage_agent import run_triage_cycle, MODEL
from datetime import datetime


def demo():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set.")
        print("Please set your API key before running this script.")
        print("Example (Windows): $env:GEMINI_API_KEY='your_api_key'")
        return

    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    
    store = PatientStore()

    print("=" * 60)
    print("  TRIAGE ORCHESTRATOR AGENT — DEMO")
    print(f"  Model  : {MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    # ── Cycle 1: baseline queue (token order wrong) ────────────────────────
    print("\n[Demo] Cycle 1 — queue is in token order, acuity is not respected.\n")
    run_triage_cycle(client, store, cycle=1)

    # ── Simulate a new emergency patient arriving ──────────────────────────
    print("\n[Demo] A new patient just checked in at the front desk...")
    store.add_patient(Patient(
        id="P005",
        name="Kumar R.",
        age=62,
        token="A005",
        chief_complaint="Sudden onset confusion, slurred speech, left-sided facial droop — started 20 min ago",
        arrived_at=datetime.now().strftime("%H:%M"),
        phone="+91-97654-00001",
        vitals={"bp": "185/110", "hr": 88, "spo2": 95, "temp": 98.6},
    ))
    print(f"[Demo] Kumar R. added. Queue now has {len(store.get_queue())} patients.\n")

    # ── Cycle 2: agent detects stroke patient, re-prioritises ──────────────
    print("[Demo] Cycle 2 — agent detects high-acuity stroke patient.\n")
    run_triage_cycle(client, store, cycle=2)

    # ── Print audit logs ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT LOG SUMMARY")
    print("=" * 60)

    print(f"\nReshuffles performed : {len(store.get_action_log())}")
    print(f"SMS messages sent    : {len(store.get_sms_log())}")
    print(f"Doctor notifications : {len(store.get_doctor_log())}")

    print("\n── Final queue order ──")
    for p in store.get_queue():
        print(f"  {p.position}. {p.name:15} | Age {p.age} | {p.chief_complaint[:55]}")

    print("\n── SMS log ──")
    for sms in store.get_sms_log():
        print(f"  -> {sms['phone']}: {sms['message'][:80]}")

    print("\n── Doctor alerts ──")
    for alert in store.get_doctor_log():
        print(f"  [{alert['priority'].upper()}] {alert['message'][:100]}")


if __name__ == "__main__":
    demo()