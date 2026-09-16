# Audit Universe — Entity Form Specification

**Status:** Approved; PRs 1-5 implemented on `feat/audit-universe-v2`. Only PR 6 (the breaking column drops, migrations `0054`-`0055`) remains, and it is deliberately held to release *N+1*.
**Author:** Engineering (with Claude)
**Date:** 2026-09-16
**Applies to:** `iams-backend` (`iams.models.AuditableEntity` and friends), `iams-frontend` (`src/components/audit-universe/*`, `src/pages/AuditableEntity*`)
**Supersedes:** the field set currently rendered by `src/components/audit-universe/EntityForm.tsx`

---

## 1. Purpose

Define the complete, production-grade field model and form design for an auditable entity in the
Audit Universe, so that:

1. The universe conforms to **IIA Global Internal Audit Standards (2024, effective 9 Jan 2025)**,
   specifically Standard 9.1 (Understanding Governance, Risk Management and Control Processes),
   **9.4 (Internal Audit Plan)** and **9.5 (Coordination and Reliance)**.
2. Every field on the form is either (a) an **input** that feeds a downstream calculation, or
   (b) **derived** and displayed read-only. Nothing is collected and then ignored.
3. The risk-scoring engine we already built (`RiskFactor` / `RiskScoringModel` / `EntityRiskScore`)
   is actually reachable from the universe UI.
4. The annual plan can be generated **capacity-constrained**, not just top-N.

### 1.1 Research basis

| Source | What we took from it |
|---|---|
| IIA, *Developing a Risk-Based Internal Audit Plan*, 2nd ed. (Global Practice Guide, 2025) | The mandate that "the **objectives, initial scope, and resources** for each auditable unit should be clearly defined" (p.10); the auditable-unit taxonomy; the Appendix F risk-factor library and weights; Appendix D universe categories; risk-based frequency bands (p.20); Appendix G plan summary shape (staff hours split IA / service provider) |
| IIA Global Internal Audit Standards 2024, Std 9.4 | Plan must be based on a *documented* assessment of strategies, objectives and risks, refreshed at least annually; must identify the **human, financial and technological resources** necessary; must consider IT governance, fraud risk, compliance/ethics program coverage |
| IIA Std 9.5 | Coordination with, and reliance on, other assurance providers — requires us to record who else covers an entity |
| Ideagen Pentana (audit universe & risk-based planning) | Two-dimensional universe (Entity × Process); entity-process attributes: *Fixed Audit Frequency, Budget Effort, Owner (staff), Business Owner (contact), Comments*; a maintainable **library of global risk factors** with Name / Description / Guidance / **Weight** / Active state; planning factors: fixed frequency, last audit rating, planning risk rating, entity risk rating; capacity compared against total budget effort — *the tool suggests, management decides* |
| Wolters Kluwer TeamMate+ | Configurable scoring settings per assessment; configurable dimensions aligned to COSO/COBIT or region |
| AuditBoard OpsAudit | Centralised universe with entities ↔ audits ↔ risks ↔ issues as two-way links; end-user configurability |
| Practitioner audit-universe register templates | Entity ID, name, category, process owner, six 1–5 inherent-risk dimensions, control-environment maturity, time since last audit, composite score, rating, planned cycle, last/next audit date |
| `docs/IAMS-Requirements-Document.md` §3.2–3.4 | FR-AU-01..06, FR-RISK-01..10, FR-PLAN-01..09 — in particular FR-AU-02's demand for Revenue, Payroll cost, Staff count, Premiums, Claims, Expenses, Assets, Legal requirements |

Two findings from the research drive most of this spec:

- **The IIA names exactly three things that must be defined per auditable unit: objectives, initial
  scope, and resources.** We currently capture none of them as first-class fields.
- **FR-AU-02 asks for materiality figures (revenue, premiums, claims, assets, payroll).** We store
  only `headcount` and `operating_budget`. Those figures are not decoration — they are the raw input
  to the "Loss / Material Exposure" risk factor, which the IIA example weights at 50% of impact.

---

## 2. Diagnosis of the current form

`EntityForm.tsx` renders 25 inputs. The problems are structural, not cosmetic.

### 2.1 Outputs are being collected as inputs

We have three risk mechanisms and the form exposes the wrong layer of all three:

| Layer | Where it lives | On the form today? |
|---|---|---|
| Risk **factor values** (the weighted, documented assessment Std 9.4 requires) | `EntityRiskScore.factor_values`, keyed by `RiskFactor.code` | **No** — only reachable from `pages/RiskModels.tsx` |
| Risk **register line items** (inherent L/I → controls → residual L/I) | `EntityRisk` → `risk_rollup.recompute_entity_risk_position` | Yes, in the Risk tab — correct |
| Risk **outputs** (rating, likelihood, impact) | resolved by `risk_rollup.resolve_entity_risk_rating`: override → engine score → residual band → default | **Yes, on the create form** — wrong |

### 2.2 Concrete defects

| # | Defect | Evidence |
|---|---|---|
| D1 | `riskRating` is a **required** create field defaulting to `"Medium"`, so every new entity is born with a hand-set rating that survives until someone adds an `EntityRisk` | `src/schemas/auditableEntity.ts:163` (`z.enum(RISK_RATINGS)`, no `.optional()`); `emptyAuditableEntityForm.riskRating = "Medium"`; `domain_serializers.py:410` `ChoiceField` with no `required=False` |
| D2 | The Likelihood/Impact boxes write `inherent_*`, but the rating badge is banded off `residual_*` — the number typed never produces the rating shown | `EntityForm.tsx` registers `inherentLikelihood`/`inherentImpact`; `risk_rollup.compute_entity_risk_position` bands `worst.effective_likelihood * worst.effective_impact` |
| D3 | Three overlapping structural pickers — `businessUnitId`, `departmentId`, `parentId` — and two disagreeing answers to "what department is this?" (`department_entity` FK vs `get_department()` walking `parent`) | `models.py:738-758` vs `models.py:890-916` |
| D4 | `compliance_status` is hand-typed, never recomputed by any workflow, and drives a headline KPI | Only writers: seeder, serializer. `views/domain.py:892` `complianceRate` |
| D5 | `estimated_man_days` is collected but read by **no** planning logic | `grep` finds it only in model / serializer / clone / import / display. `risk_engine.generate_audit_plan_draft` takes `top_n` with no capacity input |
| D6 | No human-readable entity code. `BusinessUnit` has `code`; `AuditableEntity` does not | `models.py:394` vs `models.py:723-760` |
| D7 | `primary_language` is pure serializer passthrough — zero logic reads it | `grep primary_language` → serializer + clone only |
| D8 | No objectives, no scope boundary, no assurance-coverage record, no materiality figures | IIA GPG p.10; Std 9.5; FR-AU-02 |

### 2.3 What is already right (do not regress)

- `next_audit_date` is deliberately **not** on the form — it is owned by the Audit Plan. Keep that.
- `AuditableEntityRevision` is append-only with a DB trigger (migration `0041`). Extend, don't touch.
- `RiskHistoryEntry` is append-only with a trigger (migration `0044`).
- Optimistic locking via `version` + 409. Keep.
- `EntityRisk` DB check constraints (1–5 bounds, residual ≤ inherent). Keep.
- `AuditableEntityActiveManager` hiding `Archived`, with `all_objects` escape hatch. Keep.
- The `Deprecation` header on `owner` / `department`. Keep until the sunset.

---

## 3. Design principles

**P1 — Entered vs derived is a hard contract.** A field is either typed by a human or computed by
the system. Never both, except through an explicit, rationale-bearing override that writes history.

**P2 — The form feeds the engine, it does not second-guess it.** Everything the scoring model needs
is entered here; everything the scoring model produces is displayed here read-only.

**P3 — Build in bulk, refine over time.** A universe is built 200 rows at a time. Creating an entity
must be cheap (8 fields). Completeness is then driven up by a visible readiness score, not by a wall
of required fields at create.

**P4 — Every field has a consumer.** If no filter, report, score, or plan reads a field, it does not
ship. Each row of the field table below names its consumer.

**P5 — Configurable, not hardcoded.** Insurance-specific figures (premiums, claims) belong in a
configurable metric registry, not as columns on `AuditableEntity`. The same install must serve a
bank, a telco, and an insurer.

**P6 — Defensible under review.** Anything a QA assessor or regulator could challenge — a rating, an
override, a reliance decision — carries a rationale and an immutable trail.

---

## 4. Canonical field model

Legend — **Src**: `E` entered, `D` derived (read-only), `S` system. **Req**: `R` required,
`R*` required to reach "Assessed" readiness, `O` optional.

### 4.1 Identity & classification

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Entity code | `code` | `CharField(32)`, unique, indexed | E (auto-suggested) | R | **NEW** | Bulk import key, exports, cross-references, board reporting |
| Name | `name` | `CharField(255)` | E | R | exists | Everything |
| Entity type | `entityType` | enum (expanded, §4.11) | E | R | exists, expand | Filters, tree grouping, IIA taxonomy conformance |
| Universe category | `universeCategory` | enum: `Governance`, `Operations`, `Finance`, `IT`, `Compliance`, `Support`, `Process`, `Advisory`, `ThirdParty` | E | R | **NEW** | IIA GPG Appendix D top-level taxonomy; coverage-by-category reporting to the board |
| Parent | `parentId` | FK self, cycle-guarded | E | O | exists | Hierarchy; **derives** BU + department |
| Business unit | `businessUnitId` | FK `BusinessUnit` | **D** (from ancestors; manual only on roots) | O | exists → derive | `filters.py:58`, search, BU roll-up |
| Department | `departmentId` | FK self (`Department`-type) | **D** (`get_department()`) | O | exists → derive | `filters.py:59`, dashboards |
| Status | `status` | enum Active/Inactive/Archived | E | R | exists (add to form) | `AuditableEntityActiveManager` |
| Description | `description` | Text | E | O | exists | Search |

> **D3 resolution.** The form asks for **Parent only**. `business_unit` and `department_entity` are
> populated on save by walking the ancestor chain, and shown as read-only chips with a "why" tooltip.
> A root-level entity (no parent) may set them manually. This removes the two-answers-for-one-question
> problem while keeping both columns — they stay denormalised for the existing filters and indexes
> (`ae_bu_status_idx`, `ae_dept_entity_status_idx`).

### 4.2 Mandate — the IIA triad

> *"the objectives, initial scope, and resources for each auditable unit should be clearly defined"*
> — IIA GPG, *Developing a Risk-Based Internal Audit Plan* (2nd ed.), p.10

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Audit objectives | `auditObjectives` | Text | E | R* | **NEW** | Engagement scoping seed (FR-ENG-02); plan report; Std 9.4 evidence |
| Scope — included | `scopeInclusions` | Text | E | R* | **NEW** | Prevents overlapping entities; engagement scope seed |
| Scope — excluded | `scopeExclusions` | Text | E | O | **NEW** | Coverage-gap analysis: what nobody owns |
| Linked strategic objectives | `strategicObjectiveIds` | M2M → `StrategicObjective` | E | O | **NEW** | Std 9.4 "plan must support achievement of the organization's objectives"; GPG Appendix D worksheet |

`StrategicObjective` is a small new lookup model (`code`, `title`, `description`, `owner`,
`period`, `is_active`) so the board-facing plan can show coverage per corporate objective.

### 4.3 Accountability

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Process owner (primary) | `primaryOwnerId` | FK User | E | R | exists | `coverage.withoutOwner`; notifications; `mine` filter |
| Backup owner | `secondaryOwnerId` | FK User | E | O | exists | Escalation |
| Executive sponsor | `executiveSponsorId` | FK User | E | O | **NEW** | Pentana "Business Owner (contact)"; report distribution; management-awareness factor input |
| Location | `location` | `CharField(120)` | E | O | exists | Travel/logistics; regional coverage |
| Cost centre | `costCenterId` | `CharField(64)`, indexed | E | O | exists | ERP reconciliation; `external_source` upserts |

### 4.4 Size & materiality (FR-AU-02)

Implemented as a **configurable metric registry**, not fixed columns (P5).

New models:

```
MaterialityMetricDefinition
    code            SlugField unique        e.g. "gross_written_premium"
    label           CharField(120)          e.g. "Gross written premium"
    unit            enum: currency | count | percent | fte
    currency        CharField(3) blank      ISO-4217 when unit=currency
    applies_to      JSONField list[str]     entity_type / universe_category filter; empty = all
    feeds_factor    FK RiskFactor null      which risk factor this metric informs
    display_order   PositiveSmallInteger
    is_active       Boolean indexed

EntityMaterialityValue
    entity          FK AuditableEntity  related_name="materiality_values"
    definition      FK MaterialityMetricDefinition  on_delete=PROTECT
    value           DecimalField(20, 2) null
    as_of           DateField                       period the figure refers to
    source          CharField(120) blank            "GL extract FY25", "Actuarial pack Q2"
    unique_together (entity, definition, as_of)
```

Seeded defaults (all `is_active` toggleable by an admin):

| Code | Label | Unit | Notes |
|---|---|---|---|
| `annual_revenue` | Annual revenue | currency | FR-AU-02 "Revenue" |
| `annual_expenses` | Annual operating expenses | currency | migrate `operating_budget` here |
| `payroll_cost` | Payroll cost | currency | FR-AU-02 |
| `total_assets` | Total assets | currency | FR-AU-02 |
| `headcount` | Staff count | fte | migrate `headcount` here |
| `transaction_volume` | Annual transaction volume | count | IIA factor criterion "number of transactions" |
| `gross_written_premium` | Gross written premium | currency | insurance — off by default |
| `claims_paid` | Claims paid | currency | insurance — off by default |
| `outstanding_reserves` | Outstanding claim reserves | currency | insurance — off by default |

> `headcount` and `operating_budget` stay as columns for one release (they are in
> `ordering_fields` at `views/domain.py:414-415` and in the revision tracker) and are mirrored
> into the registry. They are dropped in the follow-up release. See §11.

### 4.5 Risk assessment inputs — the factor values

**This is the biggest gap.** The form renders the **active scoring model's factors dynamically**,
reading `RiskFactor` + `RiskFactorWeight` and writing `EntityRiskScore.factor_values`.

Additions to `RiskFactor`:

| Field | Type | Why |
|---|---|---|
| `group` | enum `impact` \| `likelihood` \| `standalone` | IIA Appendix F groups factors into impact-related and likelihood-related subtotals |
| `guidance` | Text | Pentana "Guidance"; the criteria list the assessor rates against |
| `rating_anchors` | JSONField `{"1": "...", ..., "5": "..."}` | Appendix F "Ratings and Definition" column; rendered as tooltip per radio |
| `display_order` | PositiveSmallInteger | Stable form order |

Seed library (migration `0048`), lifted from IIA GPG Appendix F, Figure F.1/F.2:

| Code | Name | Group | Weight | Criteria (`guidance`) |
|---|---|---|---|---|
| `loss_exposure` | Loss / material exposure | impact | 50% | Dollar value at risk; annual operating expenses; number of transactions; impact on other areas of the organisation; degree of reliance on IT |
| `strategic_risk` | Strategic risk | impact | 50% | Public perception / reputation; local economic conditions; volatility; significance to strategy; degree of external regulation; recent legislative change; changes in business lines or services; significant new contracts |
| `control_environment` | Control environment | likelihood | 35% | Degree of process isolation; formalisation and alignment of objectives; new process/system implementation; in-house vs third-party process; operational management turnover; performance monitoring; tone at the top; formality of procedures; impact on customers |
| `complexity` | Complexity | likelihood | 35% | Degree of automation; specialisation required; level of technical detail; complexity of structure/architecture; frequency of change |
| `assurance_coverage` | Assurance coverage | likelihood | 20% | Type of engagement; other reviews (external, regulatory); second-line coverage; follow-up already in place |
| `management_awareness` | Management awareness | likelihood | 10% | Concerns expressed in surveys; concerns expressed in interviews; level of risk awareness |

Rating anchors, e.g. `control_environment`: `5 = high risk (very weak CE)` … `1 = low risk (very strong CE)`.
`assurance_coverage` anchors are recency-based: `5 = not reviewed in the last 4 years (3 for compliance or high-impact)` … `1 = reviewed in the last year or an initiative in place`.

New formula on `RiskScoringModel`:

```
FORMULA_IMPACT_LIKELIHOOD = "impact_likelihood"
# impact_subtotal    = Σ(value_i × weight_i) over group="impact"     (weights sum to 1.0)
# likelihood_subtotal= Σ(value_i × weight_i) over group="likelihood" (weights sum to 1.0)
# composite          = impact_subtotal + likelihood_subtotal          → range 2.0 .. 10.0
```

Bands (IIA Appendix F, Figure F.2 key):

| Composite | Band |
|---|---|
| 2.0 – 4.0 | Low |
| 4.1 – 6.5 | Moderate |
| 6.6 – 8.5 | High |
| 8.6 – 10.0 | Very high |

> **Compatibility.** `risk_rollup.score_to_rating` currently bands a 1–25 product into
> Low/Medium/High/Critical. That stays as the *residual worst-risk* band. The new 2–10 band applies
> only to the composite engine score. `resolve_entity_risk_rating` already prefers the engine score
> over the residual band, so the two coexist — but the band **labels must be unified**. Decision:
> keep `Low / Medium / High / Critical` as the four canonical labels (`RiskRatingChoices` is used by
> `BusinessUnit.risk_appetite`, `Audit.risk_rating`, filters, badges and the heat map); map
> IIA "Moderate"→`Medium` and "Very high"→`Critical`.

### 4.6 Assurance coverage & reliance (Std 9.5)

New child model, rendered as a repeatable row group:

```
AssuranceCoverage
    entity              FK AuditableEntity  related_name="assurance_coverage"
    provider_name       CharField(200)
    provider_type       enum: external_audit | regulator | second_line | soc_report
                            | consultant | management_testing | other
    scope               TextField blank
    last_review_date    DateField null
    next_review_date    DateField null
    reliance_level      enum: full | partial | none
    reliance_rationale  TextField blank     # required when reliance_level != none
    created/updated
```

Consumer: feeds the `assurance_coverage` risk factor (auto-suggests a rating from
`last_review_date`), drives an **assurance map** report, and evidences Std 9.5 conformance.

### 4.7 Coverage & cadence

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Audit frequency | `auditFrequency` | enum | E | R | exists | Plan generation; `coverage` |
| Frequency basis | `frequencySource` | enum `RiskBased` \| `Mandated` \| `Policy` | E | R | **NEW** | GPG p.20: cyclical/mandated engagements must be flagged so they don't look like risk-based choices |
| Suggested frequency | `suggestedFrequency` | derived | **D** | — | **NEW** | GPG p.20 bands: High/Critical ≤12 mo; Medium 19–24 mo; Low 25–36 mo. Shown next to the chosen value with a "differs from risk-based suggestion" hint |
| Mandatory to audit | `isMandatoryToAudit` | Boolean | E | O | exists | `coverage.mandatoryWithoutPlan`; KPI `planProgress` |
| Mandate reference | `mandateReference` | `CharField(200)` | E | R if mandatory | **NEW** | Names *which* law/regulation compels coverage |
| Last audit date | `lastAuditDate` | Date | E | O | exists | Staleness; `assurance_coverage` factor |
| Last audit rating | `lastAuditRating` | enum | E | O | exists | Pentana planning factor |
| Last audit period | `lastAuditPeriod` | `CharField(32)` | E | O | exists | Report labelling |
| Months since last audit | `monthsSinceLastAudit` | derived | **D** | — | **NEW** | Register column; auto-suggests `assurance_coverage` rating |
| Next audit date | `nextAuditDate` | Date | **D** (plan-owned) | — | exists | Already read-only — keep |

### 4.8 Resources (IIA triad, third leg)

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Estimated effort — IA | `estimatedIaDays` | Decimal(6,2) | E | R* | **NEW** (split) | Capacity-constrained plan generation (§8) |
| Estimated effort — co-source | `estimatedCosourceDays` | Decimal(6,2) | E | O | **NEW** | GPG Appendix G splits "Service Provider / IA / Total" |
| Estimated effort — total | `estimatedManDays` | Decimal(6,2) | **D** = IA + co-source | — | exists → becomes derived | Register column; plan capacity |
| Required skills | `requiredSkills` | JSON list of slugs (`it_general_controls`, `actuarial`, `forensic`, `data_analytics`, `treasury`, `shariah`, …) | E | O | **NEW** | Std 9.4 "identify the necessary human… resources"; GPG "Assessing Skills"; resource allocation |

> **D5 resolution.** `estimated_man_days` is not deleted — the IIA explicitly requires resources per
> auditable unit. It becomes the derived total of a two-way split and is **wired into plan
> generation** (§8). If §8 is descoped, this whole subsection is descoped with it; we do not ship a
> field with no consumer.

### 4.9 Classification & context

| Field | API name | Type | Src | Req | Status | Consumer |
|---|---|---|---|---|---|---|
| Applicable frameworks | `applicableFrameworks` | JSON multi-select: `SOX`, `COSO`, `COBIT`, `AML/CFT`, `GDPR`, `IFRS 17`, `Solvency II`, `PCI-DSS`, `ISO 27001`, local regulator… | E | O | **NEW** | **Replaces `complianceStatus`**; FR-AU-02 "Legal requirements"; FR-RISK-01 "Regulatory impact"; feeds `strategic_risk` factor |
| Key systems | `keySystemIds` | M2M → `KeySystem` (`name`, `vendor`, `criticality`, `hosting`) | E | O | **NEW** | Std 9.4 "consider coverage of information technology governance"; IT-audit scoping; feeds `complexity` factor |
| Third party | `isThirdParty` / `thirdPartyName` / `auditRightsConfirmed` | Bool / Char(200) / Bool | E | O | **NEW** | GPG p.10: *"The universe may even include critical third parties where an organization has audit rights"* |
| Fraud risk relevant | `isFraudRiskRelevant` | Boolean | E | O | **NEW** | Std 9.4 explicitly requires fraud-risk coverage to be considered in the plan |
| Tags | `tags` | JSON list | E | O | exists | `tag` / `tagsAny` / `tagsAll` filters |
| Custom fields | `customFields` | JSON list `{label, value}` | E | O | exists | Escape hatch — keep |

### 4.10 Advanced (collapsed by default)

| Field | Src | Status | Note |
|---|---|---|---|
| `primaryLanguage` | E | exists — **keep, demote** | D7 said delete; reversed. The app ships `en`/`ar`/`fr` locales, so working language of an entity's documentation is a real staffing constraint. Moves under "Advanced", default `en`, never required. |
| `externalSource` / `externalId` | S | exists | ERP provenance; read-only in UI |
| `version` | S | exists | Optimistic lock |

### 4.11 Enum changes

`EntityTypeChoices` — add, to match the IIA's stated taxonomy (*"business units, risk areas,
regulatory requirements, legal entities, branches, processes, programs, projects, systems, supply
chains… critical third parties"*):

```
+ LEGAL_ENTITY   = "LegalEntity",   "Legal entity"
+ BRANCH         = "Branch",        "Branch / site"
+ PROGRAM        = "Program",       "Program"
+ RISK_AREA      = "RiskArea",      "Risk area"
+ THIRD_PARTY    = "ThirdParty",    "Third party"
+ APPLICATION    = "Application",   "Application"
```
(keeping `Process`, `Department`, `Division`, `Area`, `System`, `Function`, `Project`, `ComplianceArea`)

`ComplianceStatusChoices` — **deleted** along with the column (§11).

### 4.12 Removed from the form

| Field | Action | Rationale |
|---|---|---|
| `complianceStatus` | **Drop column + enum** | D4. Hand-typed, never recomputed, drives a board KPI. Real posture lives in `Control` / `ControlTest` / `DeficiencyReport` / `Finding`. Replaced by `applicableFrameworks` (an input) and a derived compliance indicator (§6). |
| `riskRating` | Off the form; read-only + override action | D1. Already resolved by `resolve_entity_risk_rating`. |
| `inherentLikelihood` / `inherentImpact` | Off the form; owned by the Risk tab | D2. Entered as `EntityRisk` line items with controls and residual. |
| `businessUnitId` / `departmentId` pickers | Derived from `parentId` | D3. Columns retained. |

---

## 5. Form information architecture

### 5.1 Create — a 2-step quick-add (P3)

Goal: a new entity in under 60 seconds, because universes are built 200 rows at a time.

**Step 1 — Identify**
`code` (auto-suggested from category + sequence, editable) · `name` · `entityType` ·
`universeCategory` · `parentId` · `primaryOwnerId`

**Step 2 — Mandate**
`auditObjectives` · `scopeInclusions` · `auditFrequency` + `frequencySource` ·
`isMandatoryToAudit` (+ `mandateReference` when on)

Footer actions: **Save** · **Save and score risk** (→ §5.3) · **Save and add another** (keeps
parent + category, clears name/code — the bulk-entry path).

Derived chips shown live in step 1: resolved Business unit, resolved Department, suggested code.

### 5.2 Edit — sectioned page with a left rail

Single route (`/audit-universe/:id/edit`), left-hand section nav with per-section completeness dots,
sticky save bar, right rail carrying the derived panel (§6).

| # | Section | Fields |
|---|---|---|
| 1 | Identity | §4.1 |
| 2 | Mandate | §4.2 |
| 3 | Accountability | §4.3 |
| 4 | Size & materiality | §4.4 — repeatable metric rows, only definitions matching this entity's type/category |
| 5 | Risk assessment | §4.5 — dynamic factor cards |
| 6 | Assurance coverage | §4.6 — repeatable provider rows |
| 7 | Cadence | §4.7 |
| 8 | Resources | §4.8 |
| 9 | Classification | §4.9 |
| 10 | Advanced | §4.10 + custom fields |

Progressive disclosure: sections 4–9 collapsed by default when empty, each with a one-line summary
("3 metrics · last updated Jun 2026") so a collapsed section still reports state.

### 5.3 Risk scoring step

Rendered from the active `RiskScoringModel`. One card per `RiskFactor`, grouped
Impact / Likelihood, each showing: name, weight badge, `guidance` bullet list, a 1–5 radio row with
each anchor as its label, and an optional per-factor note.

Live panel: impact subtotal · likelihood subtotal · composite · band · projected rank in the
universe. On save → new `EntityRiskScore` row with `model_snapshot` frozen (the field already
exists, `models.py:3012`), previous `is_current` flipped false.

Auto-suggestions (pre-fill the radio, always overridable, flagged as "suggested"):
- `assurance_coverage` ← `monthsSinceLastAudit` + `AssuranceCoverage.last_review_date`
- `loss_exposure` ← percentile of this entity's currency materiality metrics across the universe

### 5.4 Rating override

Not a form field. A distinct **"Override risk rating"** action on the detail header, opening a dialog:
target rating, **required** rationale (min 20 chars), optional expiry date. On submit → sets
`risk_rating_is_overridden=True`, writes a `RiskHistoryEntry` (immutable) and an
`AuditableEntityRevision`, and stamps the badge with an "Overridden" chip that links to the rationale.
Gated at `risk_assessment` **edit** or above (§9).

### 5.5 Mobile / responsive

Left rail collapses to a `<select>` jump menu below 900px. Factor radio rows stack. Metric and
assurance repeaters become stacked cards. The sticky save bar stays.

---

## 6. The derived panel (right rail, read-only)

| Item | Source |
|---|---|
| Risk rating badge + provenance ("from scoring model *IIA Baseline v2.0*" / "from residual worst risk" / "overridden by A. Zain, 12 Jun 2026") | `resolve_entity_risk_rating` — **must start returning its source**, not just a value |
| Composite score, band, rank | `EntityRiskScore` where `is_current=True` |
| Inherent L × I / Residual L × I | `AuditableEntity.inherent_*` / `residual_*` |
| Months since last audit | derived |
| Suggested vs chosen frequency | §4.7 |
| Open findings / overdue actions | `Finding`, `CorrectiveAction` counts |
| Compliance indicator | derived from `ControlTest` results + open `DeficiencyReport` — replaces D4's hand-typed status |
| Readiness | §7 |

---

## 7. Universe readiness score

A per-entity 0–100% completeness score, surfaced on the form, the register, and the existing
`/api/auditable-entities/coverage/` page.

| Criterion | Weight |
|---|---|
| Has `primaryOwner` | 15 |
| Has `auditObjectives` | 15 |
| Has `scopeInclusions` | 15 |
| Has ≥1 materiality value | 10 |
| All active factors scored (current `EntityRiskScore`) | 25 |
| `auditFrequency` + `frequencySource` set | 10 |
| `estimatedIaDays` set | 10 |

Bands: `< 40%` Draft · `40–79%` Partial · `≥ 80%` **Assessed**.
Only **Assessed** entities are eligible for automatic inclusion in a generated plan (§8) — an
explicit, defensible gate rather than silently planning off half-empty records.

New coverage tiles: `withoutObjectives`, `withoutScope`, `withoutEffortEstimate`,
`withoutCurrentFactorScore`, `staleAssessmentOver12Months`, with matching filters on
`AuditableEntityFilter` so each tile deep-links to its offending rows (matching the existing pattern
at `filters.py:88-95`).

---

## 8. Capacity-aware plan generation

Replaces the unconstrained top-N at `risk_engine.generate_audit_plan_draft:387`.

**Request** — `POST /api/risk/generate-plan/`

```json
{
  "scoringModelId": "…",
  "year": 2027,
  "capacity": {
    "auditors": 6,
    "workingDaysPerAuditor": 230,
    "directAuditRatio": 0.65,
    "reservePercent": 0.15
  },
  "includeMandatory": true,
  "minReadiness": 80
}
```

**Algorithm**

1. `grossDays = auditors × workingDaysPerAuditor × directAuditRatio`
   `availableDays = gross × (1 − reservePercent)` — matches the 230–240 day / 60–70% direct /
   10–15% reserve convention in the planning literature.
2. **Mandated first.** All entities with `isMandatoryToAudit=True` or `frequencySource="Mandated"`
   whose cycle is due — regardless of score (GPG p.20: compulsory engagements must be included even
   when inherent risk is low). Deduct their `estimatedManDays`.
3. **Overdue cycles next.** `monthsSinceLastAudit` exceeds the band implied by the current rating.
4. **Risk rank.** Remaining entities by `composite_score` desc, `readiness >= minReadiness`,
   filling until `availableDays` is exhausted.
5. Return `{ selected[], spilled[], daysUsed, daysAvailable, reserveDays, coverageByCategory,
   coverageByStrategicObjective, unassessedExcluded[] }`.

**`spilled[]` is the point.** Pentana's own guidance is that the tool suggests and management
decides — the CAE needs the list of what did *not* fit in order to have the resource conversation
with the board (Std 10.1). The draft `ApprovalRequest` description gains a "Not included for
capacity reasons" block.

Also carried into the request payload/audit-log details: the capacity assumptions, so a year-old
plan can be re-derived.

---

## 9. RBAC

Current: the whole viewset is gated at `module = "audit_universe"`, with create/update at `edit`
(`views/domain.py:426`). That is too coarse for the new surface.

Verified against `iams/rbac_matrix.py` (role names below are the exact seeded strings):

| Role | `audit_universe` | `risk_assessment` |
|---|---|---|
| System administrator | full | full |
| Chief audit executive | **read** | approve |
| Audit manager | edit | edit |
| Senior auditor | read | edit |
| QA / quality reviewer | read | read |
| Staff auditor | none | none |
| Auditee / client manager | none | none |
| Read-only stakeholder | none | none |
| External auditor / regulator | none | none |

> **This trap was real.** The first implementation walked straight into it:
> `ModuleGatedMixin.get_permissions()` overrode everything unconditionally, so
> the `permission_classes` set on the override `@action` were silently ignored
> and the action ran on the `audit_universe` gate — locking out the CAE exactly
> as predicted. Action-level `permission_classes` now take precedence
> (`iams/permissions.py`), with the reason recorded at the call site. Any future
> `@action` that belongs to a different module than its viewset depends on that
> fix.
>
> **Trap — read this before writing the gate.** The Chief audit executive has
> `audit_universe=(READ, False)`. If the rating-override action is gated on `audit_universe` edit,
> **the CAE — the one person who most needs to override a rating — is locked out.** This is why the
> override is a separate permission rather than a level on an existing module.
>
> Equally: `risk_assessment` edit is held by **Senior auditor** as well as Audit manager. That is
> correct for entering factor scores (auditors do the scoring) but wrong for overriding a rating
> that feeds the board plan. The two must not share a gate.

| Action | Gate |
|---|---|
| View entity | `audit_universe` read |
| Edit identity / mandate / accountability / classification / cadence / resources | `audit_universe` edit |
| Enter or change **risk factor scores** | `risk_assessment` edit — reaches Senior auditor, Audit manager, CAE, sysadmin |
| **Override risk rating** | new `override_risk_rating` permission — granted to **Chief audit executive** and **Audit manager** only; System administrator reaches it via `is_super_admin` |
| Edit assurance coverage & reliance rationale | `risk_assessment` edit |
| Manage `MaterialityMetricDefinition`, `RiskFactor`, `RiskScoringModel` | `manage_settings` |
| Archive / restore | `audit_universe` full |

Enforced serializer-side: a user without the relevant gate who PATCHes a factor value or
`riskRatingIsOverridden` gets a 403 with a field-level message, not a silent drop.

## 10. Audit trail

Extend `AuditableEntityViewSet._REVISION_TRACKED_FIELDS` (`views/domain.py:503-534`) with:
`code`, `universe_category`, `audit_objectives`, `scope_inclusions`, `scope_exclusions`,
`frequency_source`, `mandate_reference`, `estimated_ia_days`, `estimated_cosource_days`,
`required_skills`, `applicable_frameworks`, `is_third_party`, `third_party_name`,
`audit_rights_confirmed`, `is_fraud_risk_relevant`, `executive_sponsor_id`.

Remove: `compliance_status`, `operating_budget`, `headcount` (once §11 drops them),
`inherent_likelihood`, `inherent_impact` (no longer user-set here).

Child-model changes (`EntityMaterialityValue`, `AssuranceCoverage`) write their own revision entries
via the same `_record_revision` helper with a `changes` key namespaced
(`materiality.gross_written_premium`, `assurance.<provider>`), so the Revisions tab stays one stream.

Rating overrides additionally write `RiskHistoryEntry` with `reason` = the rationale — the model
already has the field (`models.py:1200`) and the immutability trigger (migration `0044`).

---

## 11. Data model changes & migration sequence

Current head: `0046_riskassessmentrecord_entity_and_more`.

| # | Migration | Contents | Risk |
|---|---|---|---|
| `0047` | `audit_universe_v2_schema` | Add all new **nullable** columns to `AuditableEntity`; create `StrategicObjective`, `KeySystem`, `MaterialityMetricDefinition`, `EntityMaterialityValue`, `AssuranceCoverage`; add `group`/`guidance`/`rating_anchors`/`display_order` to `RiskFactor`; extend `EntityTypeChoices`; add `impact_likelihood` formula choice; add `materiality_cache` JSONB + GIN index (decision 1) | Additive — safe, no downtime |
| `0048` | `risk_override_access` | Raise "Audit manager" to Approve on `risk_assessment`, so the rating-override gate excludes Senior auditor (see revised decision 3) | Data-only, idempotent, reversible |
| `0049` | `seed_risk_factor_library` | Seed the six IIA factors + `IIA Baseline v2.0` scoring model (**`is_active=False`**) + `MaterialityMetricDefinition` defaults (insurance metrics inactive) | Data-only, idempotent, reversible |
| `0050` | `backfill_entity_codes` | Generate `code` for every row: `<category prefix>-<zero-padded seq>` (e.g. `OPS-0042`), collision-safe; log any manual-fix rows | **Snapshot first.** Long-running on large universes — batch in chunks of 500 |
| `0051` | `derive_structural_links` | For every entity with a `parent`, recompute `business_unit` and `department_entity` from the ancestor chain; report (do not auto-fix) rows where the stored value disagreed | **Snapshot first.** Read-heavy; run in a maintenance window |
| `0052` | `migrate_materiality_values` | Copy `headcount` → `EntityMaterialityValue(headcount)`, `operating_budget` → `EntityMaterialityValue(annual_expenses)`, `as_of = today`, `source = "migrated"` | Data-only |
| `0053` | `migrate_inherent_risk_to_register` | For entities with `inherent_likelihood`/`inherent_impact` set **and zero `EntityRisk` rows**, create one `EntityRisk` titled "Migrated inherent assessment" carrying those values, so nothing is lost when the fields leave the form | Data-only; guarded by the zero-risks condition |
| `0054` | `retire_compliance_status` | Archive each entity's `compliance_status` into a final `AuditableEntityRevision` entry, then drop the column, the enum, the index `ae_compliance_idx`, the filter, the `ordering_fields` entry, and the `complianceRate` KPI | **Breaking.** Coordinate with FE release |
| `0055` | `finalize_v2_constraints` | `code` → `unique=True, blank=False`; `NOT NULL` on `universe_category`; drop `headcount` / `operating_budget` columns | **Breaking.** Only after `0050`/`0052` verified in prod |

### Archived rows are in scope for every backfill

`AuditableEntity.objects` is an active manager that hides `Archived` rows;
`all_objects` is the escape hatch. Both the read **and the write** side of every
backfill must go through `all_objects` (`iams.backfills._entity_manager`).

This is not theoretical. A `bulk_update` through the default manager silently
skips archived entities, which then fail the `NOT NULL` check when `0055` makes
`code` required — with nothing in the deploy log explaining why. Django's
historical models carry only a plain manager, so a migration run masks the bug
entirely and it appears only when the management command is used. There is a
regression test (`test_codes_are_assigned_to_archived_entities_too`).

**Deploy gates** (matching our existing practice for the `0031-0033` department merge and the
`0034-0040` RBAC matrix):

- Snapshot before `0050`, `0051`, `0054`, `0055`.
- Django migration names must sort lexically in a single sequence, so the
  originally-planned `0047a` is `0048` and everything after it shifts by one.
- `0047`–`0053` ship in release *N* and are **backward compatible** — the old FE keeps working.
- `0054`/`0055` ship in release *N+1*, only after the new FE is live and the `Deprecation` header
  shows no remaining legacy `compliance_status` readers.
- `0050`/`0051` run in a maintenance window; everything else is online-safe.
- Each of `0050`–`0053` must be re-runnable (idempotent) so a partial failure can be replayed.

---

## 12. API changes

### New / changed endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/risk-factors/?active=1` | Drives dynamic factor rendering (code, name, group, weight, guidance, anchors, scale) |
| `PUT` | `/api/auditable-entities/{id}/risk-factors/` | Body `{scoringModelId, factorValues, notes}` → creates a new `EntityRiskScore`, flips `is_current`. Gated `risk_assessment` edit |
| `POST` | `/api/auditable-entities/{id}/override-rating/` | Body `{rating, rationale, expiresOn?}` → sets override, writes `RiskHistoryEntry` + revision. Gated `override_risk_rating` |
| `DELETE` | `/api/auditable-entities/{id}/override-rating/` | Clears the override, returns the entity to auto-resolution |
| `GET` | `/api/auditable-entities/{id}/readiness/` | Per-criterion breakdown (§7) |
| `GET/POST/PATCH/DELETE` | `/api/auditable-entities/{id}/materiality/` | Metric values |
| `GET/POST/PATCH/DELETE` | `/api/auditable-entities/{id}/assurance-coverage/` | Provider rows |
| `GET` | `/api/materiality-metrics/` | Active definitions, filtered by entity type/category |
| `GET/POST` | `/api/strategic-objectives/`, `/api/key-systems/` | Lookups |
| `POST` | `/api/risk/generate-plan/` | Extended with `capacity`, `includeMandatory`, `minReadiness`; returns `spilled[]` (§8) |

### Serializer changes (`domain_serializers.py`)

- `riskRating` → `read_only=True`. Writes are refused with a message pointing at the override
  endpoint. *(Fixes D1 at the API layer, which is where it actually matters — the import path and
  any external client bypass the FE schema.)*
- `inherentLikelihood` / `inherentImpact` → `read_only=True`.
- `complianceStatus` → accepted but ignored for one release with a deprecation warning, then removed.
- `businessUnitId` / `departmentId` → writable only when `parentId` is null; otherwise recomputed.
- `estimatedManDays` → `read_only=True`, derived from the two new fields.
- New: `code`, `universeCategory`, `auditObjectives`, `scopeInclusions`, `scopeExclusions`,
  `frequencySource`, `mandateReference`, `estimatedIaDays`, `estimatedCosourceDays`,
  `requiredSkills`, `applicableFrameworks`, `isThirdParty`, `thirdPartyName`,
  `auditRightsConfirmed`, `isFraudRiskRelevant`, `executiveSponsorId`, `strategicObjectiveIds`,
  `keySystemIds`, plus read-only `readiness`, `suggestedFrequency`, `monthsSinceLastAudit`,
  `ratingSource`.
- `AuditableEntityListSerializer` gains `code`, `universeCategory`, `readiness`, `compositeScore` —
  these are register columns and must not trigger an N+1. Add
  `Prefetch("risk_scores", queryset=EntityRiskScore.objects.filter(is_current=True))` to
  `get_queryset`.

### Filters (`filters.py`)

Add: `universeCategory`, `frequencySource`, `applicableFramework`, `requiredSkill`, `isThirdParty`,
`isFraudRiskRelevant`, `readinessBelow`, `withoutObjectives`, `withoutScope`,
`withoutEffortEstimate`, `withoutCurrentFactorScore`, `staleAssessmentOverMonths`,
`strategicObjective`, `keySystem`.
Remove: `complianceStatus` (release *N+1*).
Extend `filter_q` to cover `code`.

---

## 13. Bulk import & export

`tasks/bulk_import.py` `COLUMN_ALIASES` gains headers for every new field. Keep every existing alias
for back-compat. Specific handling:

- `"compliance status"` → no longer maps. Row-level warning: *"Compliance status was retired; use
  'Applicable frameworks'. Value ignored."* (warning, not error — a stale template must not fail the job).
- `"risk rating"` → imports **only** when a new `"rating override rationale"` column is present;
  otherwise warning + ignored. This closes the import-path hole that the FE fix alone would leave.
- `"likelihood"` / `"impact"` → create a `EntityRisk` "Imported inherent assessment" row rather than
  writing the entity columns directly.
- `"entity code"` → becomes the **preferred upsert key**, ahead of the `(external_source,
  external_id)` pair and the name fallback.
- Factor values: `"factor: loss exposure"`, `"factor: complexity"`, … → one `EntityRiskScore`.
- Materiality: `"materiality: gross written premium"`, … → `EntityMaterialityValue` rows.

New downloadable template (`GET /api/auditable-entities/import-template/?format=xlsx`) with the full
column set, an enum-values sheet, and a factor-guidance sheet so the spreadsheet carries the rating
anchors. The existing `export` action mirrors the same columns so export → edit → re-import round-trips.

---

## 14. i18n

Three locales ship (`en`, `ar`, `fr`; `ar` is RTL). New keys under `auditUniverse.form.*`:

- ~45 `field.*` keys, ~10 `section.*`, ~15 `validation.*`, ~8 `readiness.*`, ~6 `override.*`
- `riskFactor.<code>.name` / `.guidance` / `.anchor.<1..5>` — factor copy is **content, not chrome**;
  seed English into the DB (`RiskFactor.name`/`guidance`) and let i18n override by code, so an admin
  who adds a custom factor doesn't need a code change.
- RTL check: the factor radio row, the weight badges, the composite-score readout, and the
  left-rail section nav all need an `ar` pass.

---

## 15. Rollout

| PR | Scope | Ships |
|---|---|---|
| **1** | Migrations `0047`–`0049`; new models; serializers additive; new read endpoints; filters. No FE change | Release *N* |
| **2** | Backfills `0050`–`0053`. Logic lives once in `iams/backfills.py` and is driven both by the migrations (historical models) and by `manage.py backfill_audit_universe` (real models, `--dry-run`, `--only <step>`), so a large universe can be done in the window and the migrations then find nothing to do | Release *N* |
| **3** | FE: create wizard, sectioned edit page, derived rail, readiness. Old fields still accepted | Release *N* |
| **4** | FE + BE: factor-scoring step, override dialog, `risk_assessment` gating, `riskRating`/`inherent*` read-only at the API | Release *N* |
| **5** | Capacity-aware plan generation; `spilled[]`; plan report changes | Release *N* |
| **6** | Migrations `0054`–`0055`: retire `compliance_status`, `headcount`, `operating_budget`; drop deprecated filters/KPI | Release *N+1* |

Feature flag `AUDIT_UNIVERSE_V2` gates PRs 3–5 so the new form can be dark-launched to the internal
audit team before the wider rollout.

---

## 16. Test plan

**Backend**
- `test_audit_universe.py` — extend: code generation uniqueness & collision handling; structural
  derivation from a 4-deep hierarchy including a cycle attempt; `riskRating` write rejected with 403;
  override endpoint writes both `RiskHistoryEntry` and revision; readiness arithmetic at each band edge.
- New `test_risk_factor_scoring.py` — `impact_likelihood` formula against **the IIA Appendix F worked
  example** (Unit 1 → 3.25, Unit 2 → 7.5, Unit 3 → 7.15, Unit 4 → 9.55, Unit 5 → 6.4). This is the
  single most valuable test in the suite: it pins our engine to a published reference.
- New `test_plan_capacity.py` — mandated-first ordering; overdue-cycle promotion; exhaustion produces
  a non-empty `spilled[]`; reserve is never consumed; unassessed entities excluded and reported.
- Migration tests — `0050`–`0053` idempotent on re-run; `0053` does not touch entities that already
  have risks.
- RBAC matrix test — each of the nine roles against the new gates.

**Frontend**
- `EntityForm.test.tsx` — rewrite for the wizard; assert `riskRating`, `inherentLikelihood`,
  `inherentImpact` are **absent** from the create payload; assert derived chips update on parent change.
- New `RiskFactorStep.test.tsx` — renders from a mocked factor list; subtotal/composite maths;
  suggestion pre-fill is overridable and flagged.
- `a11y-forms.test.tsx` — extend to the wizard and the repeatable rows (each repeater row needs a
  labelled group; the radio rows need `role="radiogroup"` + `aria-describedby` on the anchors).
- RTL snapshot for `ar` on the factor step.

---

## 17. Decisions

Locked 2026-09-16. Recorded here so the rationale survives the conversation.

| # | Decision | Chosen | Consequence |
|---|---|---|---|
| 1 | Materiality storage | **Configurable metric registry** (§4.4) | `MaterialityMetricDefinition` + `EntityMaterialityValue`. Insurance metrics ship `is_active=False`. Costs ~2 days more than fixed columns; keeps the product sector-neutral. Ordering/filtering on a metric needs a join or a denormalised cache — see note below. |
| 2 | Capacity-aware planning (§8) | **In scope this cycle** | §4.8 resource fields stay. `generate_audit_plan_draft` gains capacity inputs and returns `spilled[]`. PR 5 is committed, not optional. |
| 3 | RBAC granularity (§9) | **Split gates** | New `override_risk_rating` permission; factor scoring moves to `risk_assessment` edit. Requires a row in the 9x11 matrix → an extra migration, sequenced as `0047a` below. |
| 4 | Band labels (§4.5) | **Map, don't rename** | IIA "Moderate"→`Medium`, "Very high"→`Critical`. `RiskRatingChoices` is untouched, so `BusinessUnit.risk_appetite`, `Audit.risk_rating`, every filter, badge and the heat map keep working. |
| 5 | `BusinessUnit` model | **Keep for now** | Revisit after v2 lands. Collapsing it into the tree would remove the last structural ambiguity but touches `seed_audit_universe`, `risk_appetite` and every BU filter — not worth bundling into this change. |

### Consequences of decision 1 (registry)

`views/domain.py:414-415` currently exposes `headcount` and `operating_budget` in `ordering_fields`.
Once those move into the registry, "sort the register by revenue" becomes a join. Two options, and
we take the second:

- Sort via `Subquery`/`OuterRef` on `EntityMaterialityValue` per requested metric — correct but slow
  on a large universe and awkward to index.
- **Denormalised sort cache:** a single `materiality_cache` JSONB column on `AuditableEntity`,
  written by the same service that writes `EntityMaterialityValue`, holding
  `{"<definition_code>": <numeric value>}` for the current `as_of`. Sorting and range-filtering read
  the cache (GIN-indexed); the child table stays the source of truth and the audit trail. The cache
  is rebuilt by a management command, so a drift bug is recoverable without a migration.

`materiality_cache` ships in migration `0047`; the rebuild command
(`manage.py rebuild_materiality_cache`, backed by `iams/materiality.py`) shipped
in PR 1 rather than PR 2, since the write path needed it immediately.

### Consequences of decision 3 (split gates) — revised during implementation

The spec originally called for a standalone `override_risk_rating` permission
granted through `Role.permissions`. **That would never have worked.** Reading
`iams/permissions.py:35-45` and `iams/rbac_matrix.py:227`, the `Role.permissions`
M2M is effectively dead: `HasPermission` resolves every key through
`LEGACY_PERMISSION_MAP` and returns `False` for any key not in it, and
`derived_permission_keys` only ever emits legacy keys. A new key granted via the
M2M would silently deny everyone except `is_super_admin`.

**What shipped instead:** the override is gated at
`ModuleAccess("risk_assessment", "approve")`, and `"Audit manager"` is raised
from Edit to Approve on that module (migration `0048_risk_override_access`).

This is better than the original plan on every axis:

| | Standalone permission | `risk_assessment` = approve |
|---|---|---|
| Works with the existing gate | No — dead M2M | Yes |
| New module column in the matrix UI | Yes (9×12) | No (9×11 unchanged) |
| Excludes Senior auditor | Only by careful grant | Automatically — they hold Edit, and `ACCESS_RANK` puts Approve above it |
| Includes the CAE | Needs an explicit grant | Already held |
| Semantics | A bespoke flag | "Approve" already means sign-off authority |

Two facts made this safe to do, both verified before the change:

- `risk_assessment=approve` currently gates **nothing** — grepping
  `iams/views/domain.py` finds eleven `module = "risk_assessment"` viewsets and
  one explicit `ModuleAccess("risk_assessment", "read")`, none at Approve. So
  the level was inert and free to claim.
- `APPROVE` outranks `EDIT` in `ACCESS_RANK`, so raising Audit manager is a
  widening only — nothing they could do before is withdrawn.

**The trap this avoids** is recorded in §9 and is worth repeating: the Chief
audit executive holds `audit_universe=(READ, False)`. Any gate hung off
`audit_universe` edit would have locked the CAE out of the one action that most
needs their sign-off.

`test_rbac_matrix.py` gains negative cases for Senior auditor (holds
`risk_assessment` edit, must **not** reach the override) and Chief audit
executive (holds only `audit_universe` read, must **still** reach it).

## Appendix A — Field count

| | Today | Proposed |
|---|---|---|
| Inputs on create | 25 (one page) | 10 (two steps) |
| Inputs on edit | 25 | ~45 across 10 collapsible sections |
| Derived, read-only | 0 shown | 9 |
| Columns dropped | — | 3 (`compliance_status`, `headcount`, `operating_budget`) |
| New models | — | 6 (`StrategicObjective`, `KeySystem`, `MaterialityMetricDefinition`, `EntityMaterialityValue`, `AssuranceCoverage`, + `RiskFactor` extensions) |

## Appendix B — Traceability

| Requirement | Satisfied by |
|---|---|
| FR-AU-01 | §5.1 |
| FR-AU-02 | §4.4 (registry covers Revenue, Payroll, Staff count, Premiums, Claims, Expenses, Assets) + §4.9 (`applicableFrameworks` = "Legal requirements") + §4.7 |
| FR-AU-03 | §4.1 `parentId`, derived BU/department |
| FR-AU-04 | §10 |
| FR-AU-05 | §13 |
| FR-AU-06 | §12 filters |
| FR-RISK-01 | §4.5 factor library |
| FR-RISK-02 | §4.5 `impact_likelihood` + weights |
| FR-RISK-03/04 | `EntityRiskScore.composite_score` / `rank` |
| FR-RISK-05 | §8 |
| FR-RISK-06 | `EntityRiskScore` append-only + `model_snapshot` |
| FR-RISK-07 | existing heat map, fed by §4.5 |
| FR-RISK-08 | §8 step 4 + `is_high_risk` |
| FR-RISK-10 | §4.5 + existing `EntityRisk` |
| FR-PLAN-01 | §8 |
| FR-PLAN-02 | §5.4 override with rationale |
| FR-PLAN-03 | §8 `coverageByCategory` |
| FR-PLAN-04 | `BusinessUnit.risk_appetite` + §8 bands |
| IIA Std 9.4 | §4.2 (objectives/scope), §4.8 (resources), §4.9 (IT, fraud, compliance coverage), §8 (documented, annual, dynamic) |
| IIA Std 9.5 | §4.6 |
