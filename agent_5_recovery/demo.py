"""
demo.py
=======
Runs a single Recovery Guardian cycle immediately — no 24-hour sleep.
Mirrors the demo.py style of agents 1, 2, and 3.

Three discharged patients pre-loaded:
  REC-001  Meena Krishnan  (58F) — Day 4, latest check-in: WORSE (fever returning)
  REC-002  Ravi Shankar    (45M) — Day 2, check-in: better, stable recovery
  REC-003  Arjun Pillai    (62M) — Day 6, check-ins all "better" BUT
                                    missed 2 consecutive critical cardiac doses

Expected behaviour:
  Meena  -> emergency SMS + doctor alert + book appointment (worsening)
  Ravi   -> medication reminder only (stable)
  Arjun  -> emergency SMS + doctor alert for missed cardiac meds (silent non-compliance)

Usage:
    python demo.py

Set GEMINI_API_KEY in your environment first.
    export GEMINI_API_KEY=your_key_here
"""

import os
from google import genai
from recovery_store import RecoveryStore
from recovery_agent import run_recovery_cycle, MODEL


def demo():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY not set.")
        print("Get a free key at: https://aistudio.google.com/app/apikey")
        return

    client = genai.Client(api_key=api_key)
    store  = RecoveryStore()

    print("=" * 60)
    print("  RECOVERY GUARDIAN AGENT — DEMO")
    print(f"  Model  : {MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)
    print()
    print("  Patients in home recovery:")
    print()
    print("  REC-001  Meena Krishnan (58F) — Day 4 post-pneumonia discharge")
    print("           Check-in trend: better -> better -> same -> WORSE (today)")
    print("           Expected: emergency SMS + doctor alert + appointment booked")
    print()
    print("  REC-002  Ravi Shankar (45M)   — Day 2 post-knee surgery")
    print("           Check-in: better. Compliant. Stable.")
    print("           Expected: medication reminder only")
    print()
    print("  REC-003  Arjun Pillai (62M)   — Day 6 post-cardiac procedure")
    print("           Check-ins all say 'better' — but missed 2 days of Aspirin")
    print("           + Atorvastatin (critical cardiac meds)")
    print("           Expected: emergency SMS for silent compliance gap + doctor alert")
    print()

    run_recovery_cycle(client, store, cycle=1)

    # Audit summary
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    escalations = store.get_escalation_log()
    sms         = store.get_sms_log()
    actions     = store.get_action_log()

    print(f"\nEscalations fired    : {len(escalations)}")
    print(f"SMS messages sent    : {len(sms)}")
    print(f"Total actions logged : {len(actions)}")

    print("\n── Escalations ──")
    if not escalations:
        print("  None.")
    for e in escalations:
        print(f"  [{e.severity.upper()}] {e.escalation_id} | {e.patient_id} | {e.reason[:70]}")

    print("\n── SMS log ──")
    for s in sms:
        print(f"  -> {s['phone']} [{s['sms_type']}]")
        print(f"     {s['message'][:100]}")

    print("\n── Action log ──")
    for a in actions:
        val = a.get("severity") or a.get("response") or a.get("summary") or ""
        print(f"  [{a['timestamp']}] {a['action']:25} | {a.get('patient_id',''):10} | {str(val)[:50]}")


if __name__ == "__main__":
    demo()