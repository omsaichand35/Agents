"""
demo.py
=======
Runs the Deterioration Sentinel Agent for one cycle immediately — no 30-min sleep.
Useful for testing and the Agent Builder Challenge demo.

What you will see:
  Cycle 1:
    • Meena Krishnan (CGH-001) — early sepsis pattern detected -> HIGH alert fired
    • Ravi Shankar   (CGH-002) — stable vitals -> no action
    • Priya Nair     (CGH-003) — SpO2 declining -> MEDIUM alert fired

Usage:
    python demo.py

Set GEMINI_API_KEY in your environment first.

Windows:  $env:GEMINI_API_KEY='your_key'
Mac/Linux: export GEMINI_API_KEY='your_key'
"""

import os
from google import genai
from sentinel_store import SentinelStore
from sentinel_agent import run_sentinel_cycle, MODEL


def demo():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set.")
        print("Get a free key at: https://aistudio.google.com/app/apikey")
        print("Then: export GEMINI_API_KEY='your_key'")
        return

    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    store  = SentinelStore()

    print("=" * 60)
    print("  DETERIORATION SENTINEL AGENT — DEMO")
    print(f"  Model  : {MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    print("\n[Demo] 3 admitted patients in the store:")
    print("  CGH-001 — Meena Krishnan, 58F, Ward 3")
    print("            Temp 37.0->37.4->37.8->38.1 | HR 78->85->94->103 | BP 118->112->104->96")
    print("            -> Classic early sepsis pattern (agent should flag HIGH)")
    print()
    print("  CGH-002 — Ravi Shankar, 45M, Ward 3")
    print("            All vitals stable, minor normal variation")
    print("            -> Agent should mark as stable (no action)")
    print()
    print("  CGH-003 — Priya Nair, 32F, ICU")
    print("            SpO2 97.0->96.2->95.1->94.0 — consistent decline over 12 hours")
    print("            -> Agent should flag MEDIUM (respiratory concern)")
    print()

    # ── Run the sentinel cycle ─────────────────────────────────────────────
    run_sentinel_cycle(client, store, cycle=1)

    # ── Audit summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    alerts   = store.get_alert_log()
    messages = store.get_message_log()
    actions  = store.get_action_log()

    print(f"\nAlerts fired         : {len(alerts)}")
    print(f"Agent messages sent  : {len(messages)}")
    print(f"Actions logged       : {len(actions)}")

    print("\n── Alerts ──")
    if not alerts:
        print("  None fired.")
    for a in alerts:
        patient = store.get_patient(a.patient_id)
        name    = patient.name if patient else a.patient_id
        print(f"\n  [{a.severity.upper()}] {name} ({a.patient_id})")
        print(f"  Alert ID  : {a.alert_id}")
        print(f"  Triggered : {a.triggered_at}")
        print(f"  Reasoning : {a.reasoning[:250]}...")

    print("\n── Agent messages ──")
    if not messages:
        print("  None sent.")
    for m in messages:
        print(f"  -> {m.to_agent} | {m.message_type} | {m.content[:80]}")

    print()


if __name__ == "__main__":
    demo()