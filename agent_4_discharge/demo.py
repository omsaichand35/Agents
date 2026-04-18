"""
demo.py
=======
Runs the Discharge Negotiator Agent for one cycle immediately — no 30-min sleep.
Useful for testing and the Agent Builder Challenge demo.

What you will see:

  DIS-001  Ravi Shankar, 45M — clinically ready, 4 blockers
           → Agent drafts discharge summary
           → Submits insurance pre-auth → approved
           → Messages pharmacy to expedite 2 medications
           → SMS family about transport
           → Sets ETA, SMS patient "You can expect to leave by X:XX PM"
           → Messages sentinel to stop monitoring, triage to prep bed

  DIS-002  Priya Nair, 32F — NOT clinically ready (vitals stable only 2h)
           → Agent calls no_action, explains, skips

  DIS-003  Meena Krishnan, 58F — ready, 1 blocker (transport)
           → Agent contacts family, resolves transport, confirms discharge

Usage:
    python demo.py

Set GEMINI_API_KEY in your environment first.

Windows:   $env:GEMINI_API_KEY='your_key'
Mac/Linux: export GEMINI_API_KEY='your_key'
"""

import os
from google import genai
from discharge_store import DischargeStore
from discharge_agent import run_discharge_cycle, MODEL


def demo():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set.")
        print("Get a free key at: https://aistudio.google.com/app/apikey")
        print("Then: export GEMINI_API_KEY='your_key'")
        return

    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    store  = DischargeStore()

    print("=" * 60)
    print("  DISCHARGE NEGOTIATOR AGENT — DEMO")
    print(f"  Model  : {MODEL}")
    print(f"  Pattern: ReAct (tool-use loop)")
    print("=" * 60)

    print("\n[Demo] 3 patients in the store:\n")
    print("  DIS-001 — Ravi Shankar, 45M, Ward 3")
    print("            Clinically ready. Vitals stable 48h.")
    print("            4 blockers: summary | insurance | pharmacy | transport")
    print("            → Agent should resolve all 4, set ETA, SMS patient + family")
    print()
    print("  DIS-002 — Priya Nair, 32F, ICU")
    print("            NOT clinically ready. Vitals stable only 2h. Still on O2.")
    print("            → Agent should call no_action and skip")
    print()
    print("  DIS-003 — Meena Krishnan, 58F, Ward 2")
    print("            Clinically ready. Insurance approved. Medications dispensed.")
    print("            1 blocker: transport only")
    print("            → Agent should contact family, resolve transport, confirm discharge")
    print()

    # ── Run one full cycle ─────────────────────────────────────────────────
    run_discharge_cycle(client, store, cycle=1)

    # ── Audit summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)

    actions  = store.get_action_log()
    sms_log  = store.get_sms_log()
    messages = store.get_agent_messages()

    blocker_resolves = [a for a in actions if a["action"] == "resolve_blocker"]
    eta_updates      = [a for a in actions if a["action"] == "update_eta"]

    print(f"\nBlockers resolved    : {len(blocker_resolves)}")
    print(f"ETA updates          : {len(eta_updates)}")
    print(f"SMS / notifications  : {len(sms_log)}")
    print(f"Agent messages sent  : {len(messages)}")
    print(f"Total actions logged : {len(actions)}")

    print("\n── Discharge ETAs ──")
    for e in eta_updates:
        p = store.get_patient(e["patient_id"])
        name = p.name if p else e["patient_id"]
        print(f"  {name}: {e['eta']}")

    print("\n── Blocker resolutions ──")
    for b in blocker_resolves:
        print(f"  [{b['blocker_type']:12}] {b['resolution'][:70]}")

    print("\n── SMS log ──")
    for s in sms_log:
        print(f"  → {s['recipient']} ({s['phone']}): {s['message'][:80]}")

    print("\n── Agent messages ──")
    for m in messages:
        print(f"  → {m.to_agent} | {m.message_type} | {m.content[:70]}")

    print("\n── Final patient status ──")
    for p in store.get_all_patients():
        open_b = store.get_open_blockers(p.patient_id)
        eta    = p.discharge_eta or "not set"
        status = "READY — all blockers cleared" if not open_b and p.clinically_ready else \
                 f"{len(open_b)} blocker(s) remaining" if p.clinically_ready else \
                 "Not clinically ready"
        print(f"  {p.name:20} | ETA: {eta:18} | {status}")

    print()


if __name__ == "__main__":
    demo()