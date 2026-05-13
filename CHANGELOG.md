# Changelog

All notable changes to the IAMS Django REST API backend.

## [0.15.0] — Phase 4 Track 3: Dashboards Backend (2026-05-12)

### Added
- **`iams/dashboards.py` service module** (FR-DASH-01..11) — pure, cacheable aggregator functions that the dashboard endpoints call:
  - `core_kpis(period?, department?)` — open-audits / overdue-findings / pending-CAPs / CAP-completion-rate. Accepts `YYYY` or `YYYY-Qn` period and free-text department.
  - `trends(period="YoY"|"FY{N}", department?)` — 8-quarter rolling YoY (or 4-quarter FY) series with `findings / auditsCompleted / capsClosed` per bucket.
  - `risk_heatmap_by_department()` — current `EntityRiskScore` rows bucketed by department × {Critical ≥80, High 60–79, Medium 40–59, Low <40}. Returns `{categories, departments, cells}`.
  - `rating_summary(period?)` — three-way rollup across QAIP `rating_overall`, ICFR `auditor_assessment` conclusions, and CSA weak-flag/average score.
  - `recent_activity(limit)` — last N `AuditLogEntry` rows (live; not cached — auditors want freshness).
  - `upcoming_audits(limit, department?)` — `start_date >= today` ordered ASC.
  - `role_bundle(role, user_email?)` — pre-composed panels for **executive / manager / auditor / auditee**. Auditor and auditee bundles slice by `user_email` ownership (`my_open_findings`, `my_open_caps`, `my_csa_responses`).
  - `cache_or_compute(key, fn, ttl=45s)` — read-through Redis cache helper, degrades gracefully when Redis is down (`IGNORE_EXCEPTIONS=True`).
  - `invalidate_dashboard_cache()` — flushes the `iams:dashboard:*` namespace; called by the beat task and ad-hoc on settings changes.
- **6 new API endpoints** at `/api/dashboard/...` (FR-DASH-02..11), all cached:
  - `GET /api/dashboard/trends/?period=YoY|FY2026&department=…`
  - `GET /api/dashboard/risk-heatmap/`
  - `GET /api/dashboard/ratings/?period=…`
  - `GET /api/dashboard/activity/?limit=…` (uncached — live feed)
  - `GET /api/dashboard/upcoming-audits/?limit=…&department=…`
  - `GET /api/dashboard/role/<executive|manager|auditor|auditee>/` (per-user cache key when role is auditor/auditee)
  - Existing `GET /api/dashboard/kpis/` now routes through the service and accepts `?period=…&department=…`.
- **Celery beat task** `iams.dashboards.refresh_caches` registered on `crontab(minute="*/5")` — warms the common dashboard payloads after invalidation so the next FE poll hits a fresh cache.
- **5 additional PDF renderers** (registered in `RENDERERS`):
  - `DepartmentRiskProfileRenderer` (FR-RPT-04) — consumes `risk_heatmap_by_department`; optional `?department=` filter.
  - `OpenIssuesRenderer` (FR-RPT-05) — every non-closed `Finding` × non-closed `CorrectiveAction`, grouped.
  - `ICFRSummaryRenderer` (FR-ICFR-05) — wraps `iams.icfr.build_icfr_summary`.
  - `QAIPAnnualRenderer` (FR-QAIP-04) — mirrors the QAIP dashboard JSON into a print-ready document; `period` required.
  - `AuditCommitteePackRenderer` (FR-DASH-11) — the board-facing roll-up: executive KPIs + trends + risk heat-map + ratings + upcoming audits in one PDF.
  - Templates land in `iams/templates/iams/reports/` and extend the shared `_base.html` (severity/status pills, KPI tiles, page footer).
- **38 new tests** in `iams/tests/test_dashboards.py` — aggregator math (KPIs, trends, heat-map, ratings, activity, upcoming), period + department filter precision, role-bundle panel composition, auditor/auditee user-scoping, cache hit-vs-miss instrumentation, every new API endpoint, every new renderer's context + filter behavior, registry-coverage check, IAMS_DISABLE_PDF_RENDER round-trip.

### Notes
- **Backend tests: 540 passing** (was 502; added 38).
- The dashboard cache uses sha256-digested kwargs JSON for stable keys (`iams:dashboard:<prefix>:<hash16>`); collisions are theoretical but the TTL bound keeps the blast radius to 45s.
- Materialized views for the slowest aggregators (heat-map + YoY trends) are deferred to Phase 5 — the current cache layer holds well under expected load (≈60s FE polls × 4 roles × ~20 concurrent users).

## [0.14.0] — Phase 4 Track 2: Report Generation Engine (2026-05-12)

### Added
- **`ReportJob` model** ([migration 0017](iams/migrations/0017_reportjob.py)) — async report-generation request. Tracks `kind`, `output_format`, `parameters` (JSON), `requested_by`, `status` (pending/running/completed/failed), `output_file` (FileField → MinIO in prod), `file_size_kb`, `error`, lifecycle timestamps.
- **`iams/reports/` renderer package** with a base class and **7 registered renderers**:
  - PDF (WeasyPrint + Jinja templates with shared base, header/footer, page-numbered footer): `AuditSummaryRenderer`, `FindingTrendsRenderer`, `CAPStatusRenderer`, `AnnualPlanRenderer`
  - Excel (openpyxl): `FindingsExcelRenderer`, `CAPsExcelRenderer`, `TimeEntriesExcelRenderer`
- **Templates** at `iams/templates/iams/reports/` with shared `_base.html` (severity/status pills, KPI tiles, page footer with counter).
- **`IAMS_DISABLE_PDF_RENDER=1` escape hatch** — emit raw HTML instead of calling WeasyPrint when system libs (pango/cairo) are unavailable. Used by the test suite and dev machines without the libs installed.
- **`iams.reports.generate_report` Celery task** — dispatches to the right renderer via the `RENDERERS` registry, writes the file, flips status, and dispatches a `Notification.KIND_GENERIC` to the requester with a deep link (success or failure).
- **API**:
  - `POST /api/reports/generate/` — `{kind, title?, parameters?}` → 201 with the new `ReportJob`. Validates kind against the registry; 400 with `supportedKinds` on unknown.
  - `GET /api/reports/jobs/` — scoped to the caller unless they hold `manage_settings` (admin sees the org); filterable by `kind` and `status`.
  - `GET /api/reports/jobs/{id}/` — poll status.
  - `GET /api/reports/jobs/{id}/download/` — 409 while pending/running, 404 when failed (with `error` body), 200 with `{url, fileSizeKb}` when completed.
- **RBAC** — `view_reports` gates all read paths; **Excel exports additionally require `export_reports`** (organization-level data leaves the system).
- **Audit log** captures `report_job_created` with kind + params as `ACTION_EXPORT`.
- **26 new tests** in `iams/tests/test_reports.py` — every renderer's context, Jinja output, Excel header+rows, filter precision, registry coverage, job lifecycle, Celery dispatch + notification, unknown-kind handling, all download states (409 pending / 404 failed / 200 completed), Excel permission gate, list scoping, RBAC matrix.

### Notes
- Five additional canonical reports (Department Risk Profile, Open Issues, ICFR Summary, QAIP Annual, Audit Committee Pack) follow the same `BaseRenderer` pattern and can be added by subclassing + adding to `RENDERERS`. Track 3 (dashboards backend) provides their aggregator endpoints first.
- **Backend tests: 502 passing** (was 476; added 26).

## [0.13.0] — Phase 4 Track 1: Configurable Risk Engine (2026-05-12)

### Added
- **Four risk-engine models** ([migration 0016](iams/migrations/0016_riskfactor_riskscoringmodel_and_more.py)) — FR-RISK-01..10:
  - `RiskFactor` — catalog of rateable dimensions (code/name/scale_min/scale_max). DB-level check on `scale_max > scale_min`.
  - `RiskScoringModel` — name/version/formula bundle with `high_risk_threshold` + active-per-name partial unique. Three formulas: `weighted_sum`, `weighted_avg`, `multiplicative`.
  - `RiskFactorWeight` — through-table; per-model factor weight.
  - `EntityRiskScore` — append-only snapshot per `(entity, scoring_model)` with `is_current` partial-unique. Holds `factor_values` JSON + computed `composite_score` (0-100 normalized) + `rank` + `is_high_risk` flag.
- **`iams/risk_engine.py` service** (FR-RISK-02..05, 07-08):
  - `compute_composite(model, factor_values)` — formula-aware, range-validated, returns Decimal in 0..100.
  - `record_score(entity, model, factor_values, by_user)` — atomic snapshot + previous-row `is_current` flip + auto-bump `entity.risk_rating` to High when composite ≥ threshold (preserves Critical).
  - `recompute_ranks(model)` — dense ranking across current scores (ties share rank).
  - `heat_map(model)` — likelihood × impact bucketed grid with per-cell entity lists.
  - `generate_audit_plan_draft(model, year, top_n, requested_by)` — top-N entities → draft `ApprovalRequest` of type Audit Plan; the existing post_save signal auto-applies the chain template (FR-PLAN-01).
  - `recompute_all_scores_for_model(model)` — bulk re-snapshot after weight/formula edits.
- **API** at `/api/risk/{factors,models,factor-weights,scores}/` plus three top-level endpoints:
  - `POST /api/risk/scores/record/` — write a new snapshot (direct CRUD on `/scores/` returns 405 to enforce single-entry).
  - `GET /api/risk/heat-map/?scoring_model_id=…`
  - `POST /api/risk/generate-plan/` — `{scoringModelId, year, topN}` → 201 with the created ApprovalRequest.
  - `POST /api/risk/models/{id}/recompute/` — bulk re-snapshot.
- **RBAC** — reads gated by `view_audits`; writes by `manage_settings`; `generate-plan` by `create_audits`.
- **Audit log** captures `risk_score_recorded`, `risk_model_bulk_recompute`, `audit_plan_generated_from_risk` with structured details.
- **32 new tests** in `iams/tests/test_risk_engine.py` — all three formulas with edge cases, range validation, missing-factor errors, current-row flip, high-risk threshold + risk_rating bump + Critical preservation, dense ranking with ties, heat-map placement, plan-draft + chain auto-apply, recompute bulk, full API + RBAC matrix.

### Test totals
- **Backend: 476 passing** (was 444; added 32).

## [0.12.0] — Phase 3 Track 4: ICFR (2026-05-12)

### Added
- **Four ICFR models** ([migration 0015](iams/migrations/0015_control_controltest_and_more.py)) — FR-ICFR-01..05:
  - `Control` — catalog entry per AuditableEntity. Framework (SOX/COSO/COBIT/Custom), type (preventive/detective/corrective), nature (manual/automated/hybrid), frequency, assertion. Unique on (entity, control_id).
  - `ControlTest` — one per (control, period, test_type). **Dual conclusions** for FR-ICFR-04 segregation: `management_assessment` + `auditor_assessment`. Computed `conclusion` property prefers auditor.
  - `ControlException` — per-sample observation with severity + M2M to `EvidenceFile`.
  - `DeficiencyReport` — OneToOne with `ControlTest`. Three classifications (control_deficiency / significant_deficiency / material_weakness) + lifecycle (draft → open → remediating → closed).
- **`iams/icfr.py` service module**:
  - `record_test_result(test, by_user, role, conclusion, notes)` — writes the right side's assessment, advances status (mgmt → in_progress, auditor → completed), and auto-creates a draft `DeficiencyReport` when the auditor concludes `deficient`. Idempotent on repeated calls.
  - `open_deficiency(deficiency, by_user, classification, ...)` — promotes draft → open with the auditor's final classification.
  - `close_deficiency(deficiency, by_user, management_response)` — final closure with management response capture.
  - `build_icfr_summary(period=None)` — aggregator: controls-by-framework, tests-by-status, tests-by-conclusion, exceptions-by-severity, deficiencies-by-classification, **openMaterialWeaknesses** rollup, totals.
- **API** at `/api/icfr/{controls,tests,exceptions,deficiencies}/` + `/api/icfr/summary/`:
  - All endpoints gated by `view_audits`.
  - Custom actions: `POST /icfr/tests/{id}/record-result/`, `POST /icfr/deficiencies/{id}/open/`, `POST /icfr/deficiencies/{id}/close/`.
- **Audit-log** captures `icfr_test_result_recorded`, `icfr_deficiency_opened`, `icfr_deficiency_closed` with structured payloads.
- **23 new tests** in `iams/tests/test_icfr.py` covering uniqueness constraints, dual-conclusion logic, auto-deficiency on failure, lifecycle transitions, exception+evidence attachment, summary math, period filter, API record-result validation, RBAC.

### Test totals
- **Backend: 444 passing** (was 421; added 23).

## [0.11.0] — Phase 3 Track 3: Control Self-Assessment (CSA) (2026-05-12)

### Added
- **Four CSA models** ([migration 0014](iams/migrations/0014_csaanswer_csaquestion_csaquestionnaire_csaresponse.py)) — FR-CSA-01..05:
  - `CSAQuestionnaire` — title, framework (COSO/COBIT/ISO 27001/Custom), version, status (draft/active/archived), `weak_threshold` (configurable per questionnaire). Unique `(title, version)`.
  - `CSAQuestion` — four response types (`yes_no`, `scale_1_5`, `text`, `evidence_required`), optional `category` (design / operating effectiveness) for split scoring, `weight` (≥1), `order`.
  - `CSAResponse` — one per business unit. Status (draft/submitted/under_review/closed), computed `score_overall` + per-category `score_design` / `score_operating`, `is_weak` boolean, lifecycle timestamps.
  - `CSAAnswer` — one per (response, question) (unique). Carries `value`, optional `evidence_file` FK, and an embedded auditor-challenge thread (`challenge_status`, `challenge_note`, `challenged_by/at`, `resolution_note`, `resolved_by/at`).
- **`iams/csa.py` service module**:
  - `compute_scores(response)` — overall + per-category 0-100 score from `weight`-weighted answer fractions.
  - `submit_response(response, by_user)` — atomic: refuses non-draft / inactive questionnaire / empty response; computes scores; flips status; if `score_overall < weak_threshold` fires side effects.
  - `open_challenge(answer, by_user, note)` — auditor opens a challenge; moves parent to `under_review`.
  - `resolve_challenge(answer, by_user, note)` — closes the challenge; rolls parent back to `submitted` when no challenges remain.
  - `close_response(response, by_user)` — auditor closes; refuses while challenges open.
- **Weak-control side effects** (FR-CSA-04): dispatches `Notification.KIND_GENERIC` to every Audit Manager via `dispatch_to_role` AND best-effort bumps the linked `AuditableEntity.risk_rating` to `High` (won't downgrade `Critical`). Both side effects are exception-swallowed so a notification failure can't roll back the submit.
- **API** (gated by `view_audits` for reads, `manage_settings` for questionnaire writes; responses + answers are `IsAuthenticated`):
  - `/api/csa/questionnaires/`, `/api/csa/questions/`, `/api/csa/responses/`, `/api/csa/answers/`
  - `POST /api/csa/responses/{id}/submit/` — locks + scores + fires weak-control signals
  - `POST /api/csa/responses/{id}/close/`
  - `POST /api/csa/answers/{id}/challenge/`
  - `POST /api/csa/answers/{id}/resolve/`
  - `?weak=true` filter on responses surfaces just the flagged ones
- **Audit-log integration** — every domain action (submit, challenge, resolve, close) records an `AuditLogEntry` with the structured event payload.
- **23 new tests** in `iams/tests/test_csa.py` covering scoring math (yes/no, scale 1-5, evidence-required), per-category split, weak-control notification + entity risk bump (with Critical preservation), full challenge workflow (open → resolve → close), and RBAC gating.

### Test totals
- **Backend: 421 passing** (was 398; added 23).

## [0.10.0] — Phase 3 Track 2: QAIP (2026-05-12)

### Added
- **Four QAIP models** ([migration 0013](iams/migrations/0013_auditkpi_qaipassessment_qaipfinding_and_more.py)) — FR-QAIP-01..06:
  - `QAIPAssessment` — internal / external / peer / post-engagement review of the IA function. Status + overall rating + lead reviewer FK + scope/methodology/summary.
  - `QAIPFinding` — *distinct* from regular `Finding`; raised against the audit function itself. Severity (critical/high/medium/low), owner (text + optional FK), recommendation, due date.
  - `StakeholderSurvey` — satisfaction (1-5) with **DB-level check constraint**, optional audit FK, role taxonomy, **anonymous** flag (scrubs the respondent FK on save AND defensively on serialise).
  - `AuditKPI` — kpi_type × period (unique constraint), target vs actual, direction (higher_is_better / lower_is_better), computed `variance` + `favorable` on read.
- **Serializers** with camelCase + computed counts (`findingsCount`, `openFindingsCount` from prefetch cache to avoid N+1) + computed `variance` / `favorable`.
- **Four QAIP ViewSets** at `/api/qaip/{assessments,findings,surveys,kpis}/` — gated by `view_reports` (read+write, matching `AuditReportViewSet` precedent). All run through `AuditedViewSetMixin` so every state change writes an `AuditLogEntry`.
- **`/api/qaip/dashboard/`** aggregate endpoint — assessments-by-type/status, open + critical QAIP findings, avg satisfaction across surveys, latest-period KPI rollup. Supports `?period=` filter.
- **18 QAIP tests** in `iams/tests/test_qaip.py` — CRUD, filters, computed counts, anonymity scrubbing on save + on serialise, DB check constraint on score range, KPI variance + favorable in both directions, uniqueness constraint, dashboard math, RBAC gating.

### Notes
- QAIP findings deliberately do **not** share a model with audit `Finding`. The two have different owners (IA team vs auditees), different lifecycles, and different reporting flows.
- Annual QAIP Report PDF generation (FR-QAIP-04 export to PDF) is deferred to Phase 4 Track 2 where WeasyPrint integration lands.
- **Backend tests: 398 passing** (was 380; added 18).

## [0.9.0] — Phase 3 Track 1: Working Papers + sign-off + versioning (2026-05-12)

### Added
- **`WorkingPaper` model** ([migration 0012](iams/migrations/0012_workingpaper.py)) — engagement-scoped audit working papers. Includes:
  - Reference + title + description + file + file_type + file_size_kb
  - Status (Draft / Under Review / Signed / Archived)
  - Version chain: `parent` self-FK, `version` integer, `is_current_version` boolean (partial unique constraint enforces one current row per (audit, reference))
  - Multi-step sign-off: `auditor_signed_by/at`, `reviewer_signed_by/at`, derived `signed_off_at`
  - Cross-references to `Finding` via M2M (FR-WP-04)
  - AV scan state mirroring `EvidenceFile` (`scan_status`, `scan_signature`, `scanned_at`, `quarantined`)
  - `searchable_text` for case-insensitive contains queries (works on Postgres + SQLite)
- **Python-level lock-on-finalize** (FR-WP-06) — `WorkingPaper.save()` rejects updates to a row with `signed_off_at` set; `delete()` raises `PermissionError`. AV scan-only updates (`scan_status`/`scan_signature`/`scanned_at`/`quarantined`) are explicitly allowed so the worker can still write its verdict after sign-off.
- **`iams/working_papers.py` service module**:
  - `sign_as_auditor(wp, by_user)` — records auditor signature; rejects double-sign.
  - `sign_as_reviewer(wp, by_user)` — records reviewer signature, sets `signed_off_at`, locks. Enforces **IIA 2330 separation of duties** (reviewer ≠ auditor).
  - `create_new_version(parent, file=, title=, description=)` — atomic: flips parent's `is_current_version` to False, inserts new row with cleared signatures + reset scan state, copies cross-references forward.
  - `populate_searchable_text(wp)` — stub extractor (real `unstructured`/`pdfplumber` integration is a follow-up).
- **`WorkingPaperViewSet`** at `/api/working-papers/`:
  - List filterable by `?audit_id=` / `?currentOnly=true` / `?status=` / `?search=`
  - `POST /` — multipart create (computes `file_size_kb`, populates `searchable_text`, dispatches AV scan)
  - `PATCH /{id}/` — rejected with **403** once signed off
  - `POST /{id}/sign/auditor/` + `/sign/reviewer/` — atomic sign-off + audit-log event
  - `POST /{id}/new-version/` — multipart; auto-flips parent's `is_current_version`
  - `GET /{id}/versions/` — full chain in order 1→N
  - `GET /{id}/download/` — signed URL; 403 on quarantine, 409 while scan pending
- **AV scan task** now recognises `model_label="WorkingPaper"` (added to `_SCANNABLE_MODELS`).
- **Audit-log events** — sign-off and new-version actions both record `AuditLogEntry` rows with the event payload (auditor_signed / reviewer_signed / new_version with parent_id + version).
- **22 working-paper tests** in `iams/tests/test_working_papers.py`.

### Notes
- Real document text extraction (PDF/Word) is deferred — the stub indexes title + description + reference + plain-text content for now. Phase 3 Track 1.1 will integrate `unstructured` (already on the dependency wishlist) + a Celery task.
- The `(audit, reference, is_current_version=True)` partial unique constraint runs on Postgres; SQLite test runs validate the Python-level guard.
- **Backend tests: 380 passing** (was 358; added 22).

## [0.8.0] — Phase 2 Track 3: Approval workflow engine + escalation (2026-05-12)

### Added
- **`ApprovalChainTemplate` model** — configurable, per-`request_type` approval chain. JSON `chain` field of `{role, sla_days}` step descriptors. DB-level unique-active constraint per request type (`iams_one_active_chain_per_type`).
- **`ApprovalStep` SLA fields** (migration 0011): `sla_days`, `due_at` (db_index), `escalated_at`.
- **`ApprovalRequest.last_action_at`** for telemetry and FE staleness badges.
- **Workflow service module** `iams/workflows.py`:
  - `apply_chain_template(request)` — expands the active template into `ApprovalStep` rows; idempotent.
  - `can_user_action(request, user)` — authorisation: approver email match, OR role match, OR super-admin bypass.
  - `advance_on_approve(request, by_user, comment)` — locked to designated approver. Advances `current_step`, promotes the next step's `due_at`, and fires the `approval_request_approved` signal when the chain completes.
  - `reject_request(request, by_user, comment)` — short-circuits + fires `approval_request_rejected`.
  - `overdue_pending_steps()` — read-only generator for the escalation task.
- **Domain signals** `approval_request_approved`, `approval_request_rejected`, `approval_step_escalated` — emitted by the workflow engine for downstream consumers.
- **Auto-apply chain on creation** — `post_save` signal expands the active `ApprovalChainTemplate` into steps whenever an `ApprovalRequest` is created without inline steps.
- **Domain-specific side-effect handlers** (in `iams/signals.py`):
  - `CAP Closure` approved → marks the CAP `Closed` + `progress=100`.
  - `Report` approved → marks the `AuditReport` `Final`.
  - `Audit Plan` approved → logs the gating transition (downstream behavior in Phase 4).
- **Escalation Celery task** `iams.workflows.escalate_overdue_steps`:
  - Stamps `escalated_at` on overdue pending steps (24h dedupe).
  - Re-pings the original approver with escalated wording.
  - Broadcasts a heads-up to every active Audit Manager via `dispatch_to_role`.
  - Records `approval_step_escalated` audit-log event (actor `system:escalation`).
  - Sends the `approval_step_escalated` signal for future consumers.
- **Beat schedule** — nightly at 03:00 local.
- **`ApprovalChainTemplateViewSet`** at `/api/approval-chain-templates/`. Reads gated by `view_audits`; writes by `manage_settings`.
- **`?mine=pending`** filter on `/api/approval-requests/` — returns requests whose current pending step matches the caller's email OR role.
- **`seed_approval_chains` management command** — seeds 5 default templates (Audit Plan, CAP Closure, Finding, Report, Risk Assessment). Idempotent; `--activate` to force-activate after seed.

### Changed
- `ApprovalRequestViewSet.approve` / `.reject` now route through the workflow service. **Unauthorised approvers get 400 with a clear "not the designated approver" message.** Audit-log events now capture the step role + final request status.
- `ApprovalStepSerializer` exposes `slaDays`, `dueAt`, `escalatedAt`, `overdue` (computed: pending AND past due_at). `ApprovalRequestSerializer` exposes `lastActionAt`.

### Test totals
- **Backend: 358 passing** (was 339; added 19 workflow tests). Coverage stable.
- Updated legacy test to satisfy the new approver-lockdown rule.

### Notes
- The Postgres `Q(escalated_at__isnull=True) | Q(escalated_at__lt=cutoff)` dedupe is checked **before** `escalated_at` is stamped in the task, so re-running mid-window is a true no-op (verified by `test_escalation_is_deduped_per_24h`).

## [0.7.0] — Phase 2 Track 2: Notifications + email pipeline (2026-05-12)

### Added
- **14-kind notification taxonomy** on `Notification.KIND_*` — `audit_assigned`, `audit_status_change`, `finding_raised`, `cap_assigned`, `cap_due_soon`, `cap_overdue`, `approval_requested`, `approval_approved`, `approval_rejected`, `password_reset`, `file_quarantine`, `weekly_digest`, `mfa_reminder`, `generic`.
- **Notification model extended** (migration 0010): `recipient` FK (NULL = system broadcast), `kind`, `target_content_type`/`target_object_id` GenericFK, `link`, `module`, `email_sent_at`, indexes on `(recipient, read, -timestamp)` + `(kind, -timestamp)`.
- **`NotificationPreference` model** — per-user × per-kind toggles for in-app and email. Unique constraint on `(user, kind)`. Defaults supplied server-side so the FE matrix is always complete on first render.
- **`iams.notifications.dispatch(...)`** — single chokepoint for every notification event. Resolves user prefs (with `DEFAULT_PREFS` fallback), writes in-app row, enqueues email task. Never raises into caller.
- **`iams.notifications.dispatch_to_role(role_name, ...)`** — fan-out helper for escalation flows.
- **`iams.tasks.notify.deliver_email`** Celery task — autoretrying, marks the originating `Notification.email_sent_at`.
- **Scheduled tasks** (`CELERY_BEAT_SCHEDULE`):
  - `iams.notify.cap_overdue_scan` — nightly at 02:00 local. Notifies CAP owners about overdue + due-in-3-days CAPs. Deduped to once-per-24h per CAP.
  - `iams.notify.weekly_digest` — Mondays at 08:00 local. Each active user gets a personalised digest (open / overdue CAPs) plus org-wide stats.
- **Email templates** at `iams/templates/iams/email/notification.{txt,html}` — responsive HTML + plain-text.
- **Signal handlers** (`iams/signals.py` connected via `IamsConfig.ready()`):
  - `CorrectiveAction.post_save` → notify owner on create
  - `Finding.post_save` → notify owner + audit lead on create (severity-aware level)
  - `AuditAssignment.post_save` → notify auditor on create
  - `ApprovalRequest.post_save` → notify submitter on approved/rejected transition
  - `ApprovalStep.post_save` → notify approver when their pending step is created
- **API endpoints**:
  - `GET /api/notifications/` is now **per-user scoped** (includes `recipient=NULL` broadcasts).
  - `GET /api/notifications/unread-count/` — tiny endpoint the FE bell polls every 60s.
  - `GET /api/notification-preferences/` — merged defaults + stored rows, one entry per kind.
  - `POST /api/notification-preferences/` — upsert by `kind`.
- **Existing `mark-read` / `mark-all-read`** actions now honor user scoping.
- **22 new notification tests** in `iams/tests/test_notifications.py` (dispatcher pref-gating, signal-driven flows, beat tasks with dedupe, API scoping, preference upsert, role broadcast).

### Configuration
- `CELERY_BEAT_SCHEDULE` declared in `config/settings/base.py` — DatabaseScheduler still wins, but these are the defaults installed on first start.

### Test totals
- **Backend: 339 passing** (was 317; added 22 notification tests). Coverage stable.

## [0.6.0] — Phase 2 Track 1: Automatic audit trail (2026-05-12)

### Added
- **`AuditedViewSetMixin`** in [iams/audit.py](iams/audit.py) — drop-in mixin for any `ModelViewSet` that captures every create/update/delete and writes an `AuditLogEntry` row with:
  - actor (display + FK), action verb, target (str + GenericFK)
  - `request_id` from middleware, IP (X-Forwarded-For aware), truncated user-agent
  - `changes` payload: `{field: {old, new}}` diff on update, `{snapshot: {...}}` on create/delete
  - Idempotent PATCH (no actual changes) does not write a row
  - Failed audit capture never breaks the user request — exception is logged and swallowed
- **`record_audit_event(...)` helper** for non-CRUD events: login, approval, password change/reset, file_quarantine, export.
- **AuditLogEntry model fields** (migration 0008): `request_id`, `ip_address`, `user_agent`, `changes` (JSON). Plus DB indexes for `-timestamp`, `(actor_ref, -timestamp)`, `(target_content_type, target_object_id)`, `(action, -timestamp)`.
- **Action verb constants** on `AuditLogEntry` — `ACTION_CREATE`, `ACTION_UPDATE`, `ACTION_DELETE`, `ACTION_APPROVE`, `ACTION_REJECT`, `ACTION_LOGIN`, `ACTION_LOGOUT`, `ACTION_PASSWORD_RESET`, `ACTION_PASSWORD_CHANGE`, `ACTION_FILE_UPLOAD`, `ACTION_FILE_QUARANTINE`, `ACTION_EXPORT`, `ACTION_OTHER`.
- **Python append-only enforcement** — `AuditLogEntry.save()` rejects updates after first INSERT (via `_state.adding`); `delete()` raises `PermissionError`.
- **DB-level append-only enforcement** (migration 0009) — Postgres `BEFORE UPDATE OR DELETE` trigger raises `iams_auditlogentry is append-only`. SQLite (test) skips the trigger; Python guard remains.
- **Privileged retention escape** — trigger respects `current_setting('iams.allow_audit_log_modification')` so the Phase 5 retention worker can purge expired rows under controlled session.
- **13 new audit-trail tests** in [iams/tests/test_audit_trail.py](iams/tests/test_audit_trail.py).

### Behavior
- Every write-able ViewSet now auto-captures:
  `AuditViewSet`, `FindingViewSet`, `CorrectiveActionViewSet`, `ChecklistItemViewSet`, `FollowUpViewSet`, `CommentViewSet`, `AuditorViewSet`, `AssignmentViewSet`, `TimeEntryViewSet`, `HoursBudgetViewSet`, `RiskAssessmentViewSet`, `ApprovalRequestViewSet`, `WorkProgramViewSet`, `WorkProcedureViewSet`, `WorkProcedureStepViewSet`, `AuditReportViewSet`, `AuditReportSectionViewSet`, `ManagedDocumentViewSet`, `UserViewSet`.
- **`ApprovalRequestViewSet.approve` / `.reject`** now record explicit `approve`/`reject` events with step role + comments in `details`.
- **`PasswordChangeView`** records `password_change`.
- **`PasswordResetConfirmView`** records `password_reset` with `via=reset_token`.
- **AV scan task** records `file_quarantine` (actor `system:clamav`) when a file is flagged.
- **User passwords** are in the global excluded-fields set — never appear in the audit log.

### Serializer
- `AuditLogEntrySerializer` now exposes: `requestId`, `ipAddress`, `userAgent`, `targetType`, `targetId`, `changes`, plus the existing `actor`/`action`/`target`/`timestamp`/`details`.

### Test totals
- **Backend: 317 passing** (was 304; added 13 audit-trail tests). Coverage stable.

## [0.5.0] — Phase 1 Track 3: MinIO storage + ClamAV virus scanning (2026-05-12)

### Added
- **Antivirus scanning of uploads** — every `EvidenceFile` and `ManagedDocument` upload is scanned asynchronously by `iams.tasks.scans.scan_uploaded_file` (Celery + `clamd` over TCP INSTREAM).
- **`clamd>=1.0.2`** dependency in `pyproject.toml`.
- New model fields on both `EvidenceFile` and `ManagedDocument` (migration 0007): `scan_status` (`pending`/`clean`/`infected`/`error`), `scan_signature`, `scanned_at`, `quarantined`. Exposed in serializers as `scanStatus`/`scanSignature`/`scannedAt`/`quarantined`.
- **`clamav` service** in `docker-compose.yml` — runs `clamav/clamav:stable` with healthcheck (note: first boot downloads ~250MB of virus definitions; `start_period: 600s`).
- **CLAMD configuration** in `config/settings/base.py`: `CLAMD_HOST` / `CLAMD_PORT` / `CLAMD_SCAN_TIMEOUT` / `CLAMD_MAX_FILE_MB` / `CLAMD_SKIP` (escape hatch for dev/CI without clamd).
- **13 scan-flow tests** in `iams/tests/test_scans.py` — clean / infected / scan error / `CLAMD_SKIP` / oversize / missing row / unknown model_label / upload-dispatches / 403-quarantined-download / 409-pending-download / clean-download / managed-document upload / managed-document-quarantined-hides-downloadUrl.

### Behavior
- **Fail-closed** — any clamd error or oversize file is marked `quarantined=True`; humans must clear it.
- **Download endpoint** (`GET /api/evidence-files/<id>/download/`) now:
  - 403 if quarantined (with `scanStatus` + `scanSignature` in body)
  - 409 if scan still pending
  - 200 with signed URL otherwise (MinIO returns presigned URL via `django-storages` when `USE_S3_STORAGE=1`; FileSystemStorage returns the absolute media URL in dev)
- **ManagedDocument `downloadUrl`** is `null` when quarantined — the FE cannot accidentally link to a virus-flagged file.
- **Rescan on file replace** — `ManagedDocumentViewSet.perform_update` resets scan state and dispatches a new scan if the `file` field changes.

### Test totals
- **Backend: 304 tests passing** (was 291; added 13 scan tests). Coverage stable.

## [0.4.0] — Phase 1 Track 2: Contract Conformance (2026-05-12)

### Added
- **`iams/tests/test_contract.py`** — **32 contract conformance tests**, one per major endpoint, asserting the JSON response shape matches the frontend's TypeScript model exactly (every camelCase field present, no snake_case leaks, list/dict types correct). This file is the **executable version** of `iams-frontend/docs/api-contract.md`.
- `cell` field on `RiskAssessmentImportIssue` model — added via [migration 0006](iams/migrations/0006_rename_sheet_name_riskassessmentimportissue_sheet_and_more.py) to match the FE contract `{sheet, cell}`.

### Fixed (drift caught by the new contract suite)
- `RiskAssessmentImportIssue` had `sheet_name` / `row_number` model fields with `sheetName` / `rowNumber` serializer keys. The FE contract expects `sheet` / `cell`. Renamed the field, added the new one, simplified the serializer.

### Changed
- `DefaultPagination.page_size` bumped 25→100 (max stays 200) so the existing FE list pages (which do not yet render pagination controls) don't silently truncate. Phase 4 dashboard work will reintroduce 25-per-page once the UI catches up.
- `order_by()` added to: `UserViewSet`, `ChecklistItemViewSet`, `EvidenceFileViewSet`, `AuditableEntityViewSet`, `FollowUpViewSet`, `AssignmentViewSet`, `HoursBudgetViewSet`, `RiskAssessmentViewSet`. Silences DRF's `UnorderedObjectListWarning` and gives paginated lists deterministic ordering.

### Notes
- All 291 backend tests passing. Coverage stable.
- Per the plan, the FE convention `pendingCAPs` (acronym preserved) was kept rather than normalized to `pendingCaps` — the FE i18n keys, mock data, and components all use the acronym form.

## [0.3.0] — Phase 1 Milestone: Auth Hardening + RBAC Matrix (2026-05-12)

### Added — Auth endpoints
- `POST /api/auth/password/reset/` — anonymous password-reset request. Always returns 202 to prevent email enumeration. Sends email via Celery (`iams.send_password_reset_email`) using `default_token_generator`.
- `POST /api/auth/password/reset/confirm/` — completes reset with `{uid, token, new_password}`. Validates token, enforces password complexity (≥12 chars by default), invalidates token on success (single-use).
- `POST /api/auth/password/change/` — authenticated password change requiring current password.
- `PATCH /api/auth/me/` — users can edit own `first_name`, `last_name`, `email` (role/status remain admin-only).
- Email templates at `iams/templates/iams/email/password_reset.{txt,html}` (plain-text + responsive HTML).
- Celery task `iams.send_password_reset_email` with autoretry (3×, exponential backoff up to 10min, jitter).

### Added — Test infrastructure
- `iams/tests/test_auth.py` — 19 tests covering every auth endpoint, including a full round-trip (request → email → confirm → new login).
- `iams/tests/test_rbac_matrix.py` — **232 tests** asserting every endpoint × every role returns the expected 200/403, plus anonymous-rejection on every endpoint. This is the central RBAC guarantee.

### Fixed
- `ChecklistItemViewSet` required `edit_audits` even for GET — drift from the API contract caught by the new RBAC matrix test. Now uses `get_permissions()` to require `view_audits` for read and `edit_audits` for write (mirrors `AuditViewSet`).
- `RiskAssessmentMatrixViewSet`, `RiskAssessmentSummaryViewSet`, `RiskAssessmentImportIssuesViewSet` — added `order_by` to silence `UnorderedObjectListWarning` and stabilize pagination.
- `drf-spectacular` post-processing hook moved to the correct `drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields` path.

### Changed
- Removed `djangorestframework-camel-case` parser/renderer from REST_FRAMEWORK defaults. The existing 30+ serializers already declare camelCase field names explicitly via `source="snake_case"` — adding the auto-translator caused double translation. Documented in `config/settings/base.py`.
- `config/settings/test.py` now also zeros out `DEFAULT_THROTTLE_RATES` so views with explicit `throttle_classes = [ScopedRateThrottle]` don't fire 429s in tests.
- Throttling on all auth-modifying endpoints is `auth_burst` (10/min) for brute-force resistance.

### Notes
- Frontend pages now reach `/api/auth/password/reset/` and `/api/auth/password/reset/confirm/` directly (no JWT required).
- All 259 backend tests passing. Coverage at 85%.

## [0.2.0] — Phase 0: Foundation Hardening (2026-05-12)

### Added
- **Settings split** — `config/settings/` package with `base.py`, `dev.py`, `prod.py`, `test.py`. Production fails fast on missing secrets; dev permits a local SQLite fallback.
- **`django-environ`** replaces `python-decouple`; supports `DATABASE_URL` parsing and proper list/bool casting.
- **OpenAPI 3.1 schema** via `drf-spectacular` + `drf-spectacular-sidecar`. Routes:
  - `/api/schema/` — raw schema (YAML/JSON)
  - `/api/docs/` — Swagger UI
  - `/api/redoc/` — ReDoc
- **Pagination** — `iams/pagination.py` with `DefaultPagination` (page 25, max 200), `LargeResultsPagination`, `AuditLogCursorPagination`. Wired as DRF default.
- **CamelCase JSON contract** — `djangorestframework-camel-case` renderer/parser pair. Python stays snake_case internally; FE sees camelCase.
- **Custom exception handler** — `iams/exceptions.py` adds `requestId` correlation to every error payload and logs unhandled exceptions to Sentry/Loki.
- **Soft delete mixin** — `iams/mixins.py` with `SoftDeleteMixin`, `SoftDeleteManager`, `SoftDeleteQuerySet`. To be applied via migration to user-facing tables in Phase 2.
- **Celery** — `config/celery.py` app + `celery[redis]`, `django-celery-beat`, `django-celery-results`, `flower`. Test-time tasks run eagerly.
- **Caching** — Redis-backed via `django-redis`. Wired in base settings with graceful degradation (`IGNORE_EXCEPTIONS=True`).
- **JWT hardening** — `simplejwt.token_blacklist` app installed, rotation enabled, `BLACKLIST_AFTER_ROTATION=True`. New endpoint: `/api/auth/token/blacklist/`.
- **Production-shape Dockerfile** — multi-stage build, non-root `iams` user, runs gunicorn + tini, healthcheck included, runtime libs only (no compilers).
- **Container entrypoint** — `docker/entrypoint.sh` dispatches `web` / `worker` / `beat` / `flower` / `migrate` / `shell` / `manage` commands.
- **Local docker-compose stack** — postgres, redis, minio (+ bootstrap that creates buckets), mailhog, backend (gunicorn), celery worker, celery beat, flower.
- **WhiteNoise** static files serving in containerized envs.
- **Object storage** — `django-storages[boto3]` for MinIO/S3. Configured in `prod.py` with SSE-AES256, signed-URL downloads (15-min expiry).
- **Observability scaffolding** — `django-prometheus` (`/metrics/`), `sentry-sdk[django]`, OpenTelemetry instrumentation packages.
- **Email pipeline** — `django-anymail[smtp]`; dev points at mailhog, prod at SMTP relay.
- **Security packages declared for Phase 5** — `django-otp`, `django-two-factor-auth`, `django-csp`, `django-axes`.
- **SSO packages declared for Phase 6** — `mozilla-django-oidc`, `hvac` (Vault client).
- **Report generation packages** — `weasyprint`, `openpyxl`, `jinja2`.
- **Test stack** — `pytest`, `pytest-django`, `pytest-cov`, `pytest-xdist`, `factory-boy`, `freezegun`, `model-bakery`, `responses`. Tests in `iams/tests/` package with `conftest.py` fixtures (RBAC users, authed clients, factories).
- **Lint/format/type-check** — `ruff` + `black` + `mypy` (with `django-stubs` + `drf-stubs`); strict mypy on `iams/views/*` and `iams/serializers`. Pre-commit config (`.pre-commit-config.yaml`) with whitespace, secret-detection, large-file, ruff, black, mypy, pip-audit (manual) hooks.
- **Smoke tests** — `iams/tests/test_smoke.py` covering health, readiness, OpenAPI schema, JWT auth, anonymous rejection.

### Changed
- `Dockerfile` rewritten as multi-stage with gunicorn entrypoint, non-root user, healthcheck.
- `docker-compose.yml` now includes redis, minio, mailhog, celery worker/beat/flower services with proper depends_on + healthchecks.
- `.env.example` rewritten with all new env vars (sections: core, CORS, DB, Redis, JWT, S3/MinIO, email, super-admin, Sentry, OIDC, Vault, Gunicorn tuning, feature flags).
- `config/wsgi.py`, `config/asgi.py` point at `config.settings.prod` by default; `manage.py` defaults to `config.settings.dev`.
- `config/urls.py` adds schema/docs/redoc/metrics routes and JWT blacklist endpoint.
- `iams/middleware.py` exports `get_current_request_id()` for use in the new exception handler.

### Removed
- Monolithic `config/settings.py` — replaced by the settings package.
- `python-decouple` — replaced by `django-environ`.

### Notes
- This release establishes the production posture. **Existing migrations are unchanged**; no data migration required.
- Next steps (Phase 1): wire FE to real backend, add password reset endpoints, switch evidence storage to MinIO, lock RBAC matrix via test suite.

## [0.1.0] — Initial release

- Django 6.0.2 + DRF + SimpleJWT + 40 models in single `iams` app + 28+ REST resources, 5 migrations, RBAC, request-ID tracing, health/ready endpoints, RBAC seed command.
