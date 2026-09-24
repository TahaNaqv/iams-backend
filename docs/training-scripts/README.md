# IAMS Training Video Scripts

Five scripts for the IAMS training-video bundle. Each script is structured as **timestamp · narration · on-screen action** so a producer can record straight through.

| File | Audience | Length | Focus |
|---|---|---|---|
| [`01-intro.md`](01-intro.md) | Everyone | ~5 min | Tour, sign-in, dashboard, language switch |
| [`02-auditor.md`](02-auditor.md) | Auditors | ~15 min | Audit lifecycle: plan → fieldwork → finding → CAP → working paper → sign-off |
| [`03-manager.md`](03-manager.md) | Audit Managers | ~10 min | Approval flow, annual plan generation, QAIP dashboard |
| [`04-auditee.md`](04-auditee.md) | Auditees | ~5 min | Receiving a CAP, attaching evidence, CSA response |
| [`05-admin.md`](05-admin.md) | IT Admin | ~15 min | User mgmt, SSO setup, integration wiring, monitoring |

## Production notes

- **Demo data:** scripts assume the seed dataset from `manage.py seed_demo` (sample audits + findings + CAPs across 3 departments).
- **Resolution:** 1920×1080, captured at 30 fps. Browser at 100% zoom; Chrome with the IAMS PWA installed for cleaner chrome.
- **Captions:** every script doubles as the closed-caption track. Translate via the same `i18n/locales/<lang>.json` keys.
- **Re-record cadence:** when a UI change touches one of the surfaces a script narrates, regenerate just that script. Don't bundle re-records — keep them per-script.
