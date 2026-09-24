# IAMS User Guide

For end users — auditors, audit managers, auditees, executives, and the audit committee.

## Contents

1. [Signing in](#signing-in)
2. [The dashboard](#the-dashboard)
3. [For Auditors](#for-auditors)
4. [For Audit Managers](#for-audit-managers)
5. [For Auditees](#for-auditees)
6. [For Executives & the Audit Committee](#for-executives--the-audit-committee)
7. [Account & security](#account--security)
8. [Languages](#languages)
9. [Getting help](#getting-help)

---

## Signing in

### Corporate SSO (recommended)

If your organization has wired up Keycloak / Active Directory SSO, click **"Sign in with corporate account"** on the login page. You'll be redirected to the corporate identity provider, authenticate with your normal AD credentials, and bounce back into IAMS. First-time SSO users are auto-provisioned with the Viewer role until an admin assigns the right one.

### Password sign-in

For service accounts and break-glass access, the password login form is always available. After 5 failed attempts your account is locked for 15 minutes; ask an admin to unlock it if needed.

### Multi-factor authentication (MFA)

If your role requires MFA, you'll be prompted to set up an authenticator app (Google Authenticator, 1Password, Authy, …) the first time you sign in:

1. Scan the QR code or copy the secret manually.
2. Enter the 6-digit code from your authenticator app to confirm enrollment.
3. **Save your backup codes** — the system shows them *once*. Each code is one-shot.

On every subsequent login you'll enter the current 6-digit code along with your password.

---

## The dashboard

The home page shows a **role-specific bundle** of widgets:

| Role | Default widgets |
|---|---|
| Executive | KPIs, YoY trends, risk heat-map by department, ratings rollup, upcoming audits |
| Audit Manager | KPIs, YoY trends, ratings, upcoming audits, recent activity |
| Auditor | My audits, my open findings, upcoming audits, recent activity |
| Auditee | My open CAPs, my CSA responses, recent activity |

KPI tiles auto-refresh every 60 seconds. Click any tile to drill into the underlying list.

---

## For Auditors

### Day-to-day flow

1. **Check "My open findings" on the dashboard** for items due in the next two weeks.
2. **Open an audit** to see its checklist, evidence, working papers, and timeline.
3. **Raise a finding** from inside the audit. Severity drives notification urgency.
4. **Open a CAP** against the finding, assign an owner, set a due date.
5. **Sign working papers** as `auditor` once your fieldwork is complete; another reviewer signs as `reviewer` (separation of duties is enforced — you can't review your own paper).

### Working papers

- Cross-reference papers using `[[paper-title]]` syntax inside the description; the link auto-resolves.
- Version a paper by clicking **"Create new version"** — the old version becomes immutable, the new one inherits the cross-references.
- Use the **"Evidence"** tab to attach files (PDF, Excel, images). Files are AV-scanned; uploads larger than 100MB are rejected.

### Risk assessment

- The Risk Workbook (under Risk Register) lets you score auditable entities using the configured scoring model.
- Composite scores normalize to 0–100; entities above the model's threshold are marked **High Risk** automatically.
- A scored entity's history is preserved as a `RiskHistoryEntry` row — auditors can see how a score has drifted.

### Reports

- Click **Reports → Generate** to produce a PDF or Excel report.
- Available kinds: Audit Summary, Finding Trends, CAP Status, Open Issues, Department Risk Profile, Annual Audit Plan, QAIP Annual, ICFR Summary, Audit Committee Pack, plus three Excel exports.
- Generation is async — you'll get a notification when it's ready with a download link.

---

## For Audit Managers

### Planning the annual audit cycle

1. **Open Risk Register → Annual Plan.** The system pre-fills it with the top-N entities by composite risk score.
2. **Adjust the plan** — add / remove entities, adjust scope per engagement.
3. **Submit for approval.** The configured approval chain template (CAE → Audit Committee Chair) is applied automatically.
4. **Track progress** on the dashboard's "Open audits" KPI.

### Approving CAPs and findings

- The **My pending approvals** widget on the dashboard shows everything awaiting your decision.
- For CAP closure: review the evidence the auditee attached, then approve / reject. Approval marks the CAP `Closed`; rejection sends it back to the auditee with your comment.
- For audit reports: same flow; approval marks the report `Final`.

### Quality assurance (QAIP)

- The QAIP dashboard shows annual / per-engagement / external assessment rollups.
- Stakeholder surveys are collected automatically after each audit; satisfaction scores feed the dashboard.
- Self-vs-external rating discrepancies are highlighted.

---

## For Auditees

### Responding to a CAP

1. **Email notification** plus an in-app alert when a CAP is assigned to you.
2. **Open the CAP** to read the recommendation + the auditor's expected outcome.
3. **Attach evidence** of your remediation (screenshots, policy doc, test result) via the Evidence tab.
4. **Update progress** as a percentage (0–100). 100% triggers an automatic "ready for closure" notification to the auditor.
5. **Optional: challenge** the finding via the **Challenge** button. A challenge starts a discussion thread with the auditor without blocking the CAP timeline.

### Control self-assessment (CSA)

- When an auditor sends you a CSA questionnaire, you'll see it in your inbox + on the dashboard.
- Answer each question — single-choice, multi-choice, rating (1–5), or text.
- Weak controls auto-create a follow-up alert to the audit manager.
- Submit when complete. You can re-open later if you find new evidence.

---

## For Executives & the Audit Committee

### The dashboard

The executive bundle shows the four top-line KPIs (Open Audits, Overdue Findings, Pending CAPs, CAP Completion %), the year-over-year quarterly trend chart, the department × risk heat map, and the rating rollup across QAIP / ICFR / CSA.

### The Audit Committee Pack

Click **Reports → Generate → Audit Committee Pack** to produce the board-facing PDF: KPIs, trends, heat map, ratings, upcoming audits — all in one document. The same data feeds the dashboard, so the numbers never diverge.

### Drilling in

Every KPI tile and every chart segment is clickable; you land on the underlying list filtered to that scope. Useful for ad-hoc questions during a board meeting.

---

## Account & security

### Change password

**Settings → Account → Change password.** The system rejects passwords that:

- Are shorter than 12 characters.
- Are too similar to your name / email.
- Are on the common-passwords list.
- Are numeric-only.
- Match any of your last 5 passwords.

### Manage MFA

**Settings → Security → MFA**:

- **Set up TOTP** — scan QR, confirm code.
- **Regenerate backup codes** — old codes are invalidated; new ones shown once.
- **Disable TOTP** — requires re-entering your password.

### Sessions

- Access tokens expire after 15 minutes; the browser silently refreshes them.
- After 60 minutes of inactivity (no API calls) the refresh token is revoked — you'll need to sign in again.
- You can sign out manually via **User menu → Sign out** (blacklists your current refresh token).

---

## Languages

IAMS ships with three locales:

- **English** (default)
- **العربية** (Arabic; RTL layout — the whole UI mirrors)
- **Français**

Switch via **User menu → Language** or the language switcher in the topbar. Your preference syncs to your profile and is restored when you sign in on another device.

---

## Getting help

- **In-app:** click the **?** icon in the topbar for context-aware help.
- **Email:** `iams-support@yourorg.example` (configured per deployment).
- **Documentation:** this guide and the [admin guide](admin-guide.md).
- **Training videos:** see [training-scripts/](training-scripts/) for the script outlines.

For technical bugs, please include:

1. The URL you were on.
2. Roughly what you were doing.
3. The "Request ID" at the bottom of any error message (the system uses this to correlate logs).
