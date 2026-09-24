# Script 03 — Audit Manager walkthrough

**Audience:** audit managers, CAEs · **Length:** ~10 min · **Pre-req:** scripts 01 + 02

The manager-specific surfaces: approval queue, generating the annual audit plan from risk scores, the QAIP dashboard, and the audit-committee pack.

---

| Time | Narration | On-screen |
|---|---|---|
| 0:00–0:30 | "This walkthrough is for audit managers and CAEs. We'll cover approvals, annual planning from the risk engine, QAIP rollups, and the audit committee pack." | Title card. |
| 0:30–1:30 | "Your dashboard shows the *My pending approvals* widget at the top. Click any row to open the approval request — it could be a CAP closure, a finalized audit report, or an annual audit plan. You'll see the chain of approvers, who's approved already, and any comments." | Manager dashboard → pending approvals → click first row. |
| 1:30–2:30 | "Review the underlying CAP — the auditee's evidence, the auditor's recommendation. If you're satisfied, click *Approve* with a comment. The approval advances to the next step in the chain; the final approver's click marks the CAP closed. Reject and the auditee gets a notification with your comment." | Open the CAP referenced. Scroll through evidence. Approve with comment. |
| 2:30–3:30 | "Different request types route through different approval chains. CAP closure goes Auditor → Manager → CAE. Annual audit plan goes CAE → Audit Committee Chair. The chains are configurable in *Settings → Approval Chain Templates* — you set the role, the SLA, and the precedence." | Open Approval Chain Templates settings. Show the CAP closure chain. |
| 3:30–4:30 | "Approvals have SLAs — if a step sits in Pending past its SLA, the system escalates. The nightly escalation task at 3 AM bumps the approver's role one level up and adds an event to the audit log. You'll see escalated items in red on the dashboard." | Show the *Escalation* indicator on a sample step. |
| 4:30–5:45 | "Annual planning. Open *Risk Register → Annual Plan*. The risk engine sorts auditable entities by composite score; the top N entities — configurable per scoring model — are pre-filled. Adjust scope, add or remove engagements, set the year." | Open Annual Plan. Show the auto-filled top-N list. |
| 5:45–6:30 | "Click *Submit for Approval*. The system creates an ApprovalRequest of type *Audit Plan* and applies the configured chain template — usually CAE → Audit Committee Chair. You can also generate the plan straight from the risk dashboard with one click." | Submit. Show the chain materialized. |
| 6:30–7:30 | "Quality assurance: open the QAIP dashboard. You see annual / per-engagement / external assessment rollups, stakeholder satisfaction (auto-collected after each audit), and self-vs-external rating discrepancies. The QAIP findings panel shows weaknesses raised against the audit function itself." | QAIP dashboard pan-around. Pause on stakeholder satisfaction trend. |
| 7:30–8:30 | "ICFR / compliance lives in its own dashboard. Controls × tests × exceptions × deficiencies. Material weaknesses are flagged red on the executive view — that's the signal the audit committee wants to see immediately." | ICFR dashboard. Highlight the material-weakness count. |
| 8:30–9:30 | "Audit committee pack. *Reports → Generate → Audit Committee Pack* produces the board-facing PDF: KPIs, year-over-year trend chart, department × risk heat map, ratings across QAIP/ICFR/CSA, upcoming audits. The same aggregator feeds both the dashboard and the PDF, so the numbers can't diverge." | Generate the pack. Wait for completion. Download and scroll through the PDF. |
| 9:30–10:00 | "That's your manager flow. Next: Auditee walkthrough for responding to CAPs and CSA questionnaires." | Outro card. |
