"""
demo.py
=======
Runs the Care Continuity Agent for two cycles immediately (no sleep).
Cycle 1: detects Amoxicillin-Clavulanate gap, substitutes, notifies all parties.
Cycle 2: detects Metoprolol administration overdue, notifies nurse.

Usage:
    python demo.py

Set GEMINI_API_KEY in your environment first.
"""

import os
from google import genai
from care_store import CareStore
from care_agent import run_care_cycle, MODEL


def demo():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set.")
        print("Please set your API key before running this script.")
        print("Example (Windows): $env:GEMINI_API_KEY='your_api_key'")
        return

    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    store  = CareStore()

    print("=" * 60)
    print("  CARE CONTINUITY AGENT — DEMO")
    print(f"  Model  : {MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    # ── Cycle 1: critical antibiotic gap ──────────────────────────────────
    print("\n[Demo] Cycle 1:")
    print("  Meena P. — Amoxicillin-Clavulanate prescribed 6h ago,")
    print("  never dispensed (pharmacy out of stock), never administered.")
    print("  Agent should: detect gap -> query pharmacy -> find substitute")
    print("  -> get doctor approval -> update prescription -> notify all.\n")
    run_care_cycle(client, store, cycle=1)

    # ── Cycle 2: administration overdue ───────────────────────────────────
    print("\n[Demo] Cycle 2:")
    print("  Arjun K. — Metoprolol dispensed but nurse has not confirmed")
    print("  administration (1h overdue). Agent should: detect gap -> notify nurse.\n")
    run_care_cycle(client, store, cycle=2)

    # ── Audit summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    actions = store.get_action_log()
    sms     = store.get_sms_log()
    gaps    = store.get_open_gaps()

    print(f"\nActions logged      : {len(actions)}")
    print(f"Notifications sent  : {len(sms)}")
    print(f"Remaining open gaps : {len(gaps)}")

    print("\n── Action log ──")
    for a in actions:
        print(f"  [{a['timestamp']}] {a['action_type']}: {str(a['detail'])[:80]}")

    print("\n── Notifications ──")
    for s in sms:
        print(f"  -> {s['recipient']} ({s['phone']}): {s['message'][:80]}")

    print("\n── Open gaps ──")
    if not gaps:
        print("  None — all gaps resolved.")
    for g in gaps:
        print(f"  {g.gap_id} | {g.severity} | {g.description[:70]}")


if __name__ == "__main__":
    demo()