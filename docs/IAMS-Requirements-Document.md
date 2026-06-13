# Internal Audit Management System (IAMS)
## Consolidated Requirements Document

*Purpose: Implementation roadmap — consolidates Audit.txt, IAMS Design Document, Proposal.txt, Requirements.txt, System Features.txt, and iams-frontend analysis.*

---

## 1. Introduction

### 1.1 Purpose
This document defines the complete functional and non-functional requirements for the Internal Audit Management System (IAMS). It serves as the master reference for implementing the system—from the existing frontend prototype through backend development, integrations, and full deployment.

### 1.2 Scope
The IAMS will:
- Enable risk-based annual audit planning
- Manage audit engagements end-to-end
- Store and secure working papers
- Track findings and management action plans (MAPs/CAPs)
- Provide real-time dashboards and analytics
- Integrate with ERP / HR / Risk systems (optional phase)
- Maintain audit trail and compliance logging
- Support cloud and on-premise deployment

### 1.3 Definitions
| Term | Definition |
|------|------------|
| CAE | Chief Audit Executive |
| MAP | Management Action Plan |
| CAP | Corrective Action Plan (same as MAP) |
| QAIP | Quality Assurance & Improvement Program |
| CSA | Control Self-Assessment |
| ICFR | Internal Control over Financial Reporting |
| ERM | Enterprise Risk Management |

---

## 2. User Roles & Stakeholders

| Role | Responsibilities |
|------|------------------|
| Chief Audit Executive (CAE) | Approvals, oversight, board reporting |
| Audit Manager | Planning, supervision, review |
| Internal Auditor | Execution, documentation |
| Auditee / Process Owner | Respond to findings and action plans |
| Senior Management | Dashboards and reports |
| System Administrator | User and system configuration |

---

## 3. Functional Requirements (by Module)

---

### 3.1 User & Access Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-UAM-01 | System shall allow creation, editing, and deactivation of users | Critical |
| FR-UAM-02 | System shall support custom roles with configurable permissions per module | Critical |
| FR-UAM-03 | System shall enforce Role-Based Access Control (RBAC) | Critical |
| FR-UAM-04 | System shall support Multi-Factor Authentication (MFA) | Critical |
| FR-UAM-05 | System shall integrate with Active Directory / SSO (optional) | High |
| FR-UAM-06 | System shall enforce configurable password complexity rules | Critical |
| FR-UAM-07 | System shall log all login attempts | Critical |
| FR-UAM-08 | System shall provide configurable session timeout | High |
| FR-UAM-09 | System shall maintain immutable audit trail of user actions | Critical |

**Roles:** Admin, Auditor, Manager, Viewer (configurable)

---

### 3.2 Audit Universe Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-AU-01 | System shall allow creation of auditable entities | Critical |
| FR-AU-02 | Each entity shall store metadata: Department, Revenue, Payroll cost, Staff count, Premiums, Claims, Expenses, Assets, Legal requirements, Last audit date, Previous rating | Critical |
| FR-AU-03 | System shall support hierarchical entity structure | High |
| FR-AU-04 | System shall maintain historical changes | High |
| FR-AU-05 | System shall allow bulk import via Excel/CSV | High |
| FR-AU-06 | System shall provide search and filter by name, department, risk | Critical |

---

### 3.3 Risk Assessment

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-RISK-01 | System shall allow definition of risk factors: Impact, Likelihood, Control maturity, Financial exposure, Regulatory impact, Reputational risk | Critical |
| FR-RISK-02 | System shall support configurable weighted scoring models | Critical |
| FR-RISK-03 | System shall automatically calculate composite risk score | Critical |
| FR-RISK-04 | System shall rank entities based on risk score | Critical |
| FR-RISK-05 | Risk score recalculation shall auto-update audit priority | Critical |
| FR-RISK-06 | System shall maintain version history of risk assessments | High |
| FR-RISK-07 | System shall generate risk heat maps | High |
| FR-RISK-08 | System shall auto-flag high-risk entities for audit plan inclusion | High |
| FR-RISK-09 | System shall import Enterprise Risk Register (Excel/API) | High |
| FR-RISK-10 | System shall map risks to auditable entities | High |

---

### 3.4 Annual Audit Planning

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-PLAN-01 | System shall generate draft annual audit plan based on risk ranking | Critical |
| FR-PLAN-02 | System shall allow manual override with documented rationale | Critical |
| FR-PLAN-03 | System shall calculate audit coverage percentage | High |
| FR-PLAN-04 | System shall allow linking Board-approved risk appetite thresholds | High |
| FR-PLAN-05 | System shall generate Annual Audit Plan Report (PDF/Word) | Critical |
| FR-PLAN-06 | System shall support approval workflow: Auditor → Manager → CAE → Board | Critical |
| FR-PLAN-07 | System shall maintain version history of approved plans | High |
| FR-PLAN-08 | System shall support filters by year, department, status, auditor | High |
| FR-PLAN-09 | System shall provide calendar view of planned audits | High |

---

### 3.5 Engagement Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-ENG-01 | System shall create engagement record linked to audit plan | Critical |
| FR-ENG-02 | System shall define objectives, scope, criteria, methodology, resources | Critical |
| FR-ENG-03 | System shall assign auditors and supervisors | Critical |
| FR-ENG-04 | System shall track milestones and deadlines | Critical |
| FR-ENG-05 | System shall track time spent per auditor | High |
| FR-ENG-06 | System shall support multi-level review and digital sign-off | Critical |
| FR-ENG-07 | Engagement cannot be closed without final approval | Critical |
| FR-ENG-08 | System shall maintain status history logs | High |
| FR-ENG-09 | System shall provide preloaded audit program templates (financial, compliance, IT, operational, ICFR) | High |
| FR-ENG-10 | System shall support status workflow: Draft → In Progress → Review → Completed | Critical |

---

### 3.6 Working Papers Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-WP-01 | System shall allow upload of documents (PDF, Excel, Word, images) | Critical |
| FR-WP-02 | System shall maintain version control for each document | Critical |
| FR-WP-03 | System shall support digital sign-off (Auditor & Reviewer) | Critical |
| FR-WP-04 | System shall allow cross-referencing findings to working papers | Critical |
| FR-WP-05 | System shall store documents with timestamp | Critical |
| FR-WP-06 | System shall prevent deletion of finalized working papers | Critical |
| FR-WP-07 | System shall provide search by engagement, entity, risk category | High |
| FR-WP-08 | System shall encrypt documents at rest | Critical |
| FR-WP-09 | System shall comply with IIA 2330 – Documenting Information | Critical |

---

### 3.7 Findings & Issue Tracking

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-FIND-01 | System shall allow creation of finding with: Risk rating (Critical/High/Medium/Low), Impact, Root cause category, Recommendation | Critical |
| FR-FIND-02 | System shall allow assignment of responsible owner | Critical |
| FR-FIND-03 | System shall allow definition of target completion date | Critical |
| FR-FIND-04 | System shall allow auditee to upload corrective action evidence | Critical |
| FR-FIND-05 | System shall require audit validation before closure | Critical |
| FR-FIND-06 | System shall auto-generate email reminders before due date | High |
| FR-FIND-07 | System shall escalate overdue findings to management | High |
| FR-FIND-08 | System shall allow reopening of closed findings | High |
| FR-FIND-09 | System shall provide aging analysis dashboard | High |
| FR-FIND-10 | System shall support root cause taxonomy: People, Process, System, Policy | High |

---

### 3.8 Corrective Action Plans (MAPs/CAPs)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-CAP-01 | System shall create CAP linked to finding | Critical |
| FR-CAP-02 | System shall assign owner and due date | Critical |
| FR-CAP-03 | System shall track status: Open, In Progress, Overdue, Closed | Critical |
| FR-CAP-04 | System shall track progress (percentage or milestone steps) | Critical |
| FR-CAP-05 | System shall allow upload of evidence of completion | Critical |
| FR-CAP-06 | System shall require management/audit approval for closure | Critical |
| FR-CAP-07 | System shall highlight overdue items | High |
| FR-CAP-08 | System shall send automated reminders and escalation | High |

---

### 3.9 Dashboard & Reporting

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-DASH-01 | System shall display audit status summary (Completed, Ongoing, Planned) | Critical |
| FR-DASH-02 | System shall display KPI cards: Open Audits, Overdue Findings, Pending CAPs, Completion Rate | Critical |
| FR-DASH-03 | System shall display audit status chart (bar/donut) | Critical |
| FR-DASH-04 | System shall display risk heat map by department | Critical |
| FR-DASH-05 | System shall display recent activity feed | Critical |
| FR-DASH-06 | System shall display upcoming audits list | Critical |
| FR-DASH-07 | System shall support filters by period, department, entity, risk | High |
| FR-DASH-08 | System shall export dashboards to PDF/Excel | High |
| FR-DASH-09 | System shall display rating summaries (Satisfactory / Needs Improvement / Unsatisfactory) | High |
| FR-DASH-10 | System shall provide year-over-year trend analytics | High |
| FR-DASH-11 | System shall generate Audit Committee reporting pack | High |

---

### 3.10 Report Templates

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-RPT-01 | System shall provide Audit Summary Report | High |
| FR-RPT-02 | System shall provide Finding Trends Report | High |
| FR-RPT-03 | System shall provide CAP Status Report | High |
| FR-RPT-04 | System shall provide Department Risk Profile | High |
| FR-RPT-05 | System shall provide Open Issues Report | High |
| FR-RPT-06 | System shall provide Annual Audit Plan Report | Critical |
| FR-RPT-07 | System shall export reports to PDF and Excel | High |

---

### 3.11 Quality Assurance & Improvement Program (QAIP)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-QAIP-01 | System shall record internal quality assessments | High |
| FR-QAIP-02 | System shall record external quality reviews | High |
| FR-QAIP-03 | System shall capture stakeholder satisfaction surveys | High |
| FR-QAIP-04 | System shall generate annual QAIP report | High |
| FR-QAIP-05 | System shall track audit KPIs (timeliness, review quality) | High |
| FR-QAIP-06 | System shall support peer reviews and post-engagement evaluations | Medium |

---

### 3.12 Control Self-Assessment (CSA)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-CSA-01 | System shall allow creation of CSA questionnaires | High |
| FR-CSA-02 | System shall allow business units to submit responses | High |
| FR-CSA-03 | System shall score control design and operating effectiveness automatically | High |
| FR-CSA-04 | System shall auto-flag weak control units for audit prioritization | High |
| FR-CSA-05 | System shall support auditor review and challenge workflow | Medium |

---

### 3.13 ICFR / Compliance Testing

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-ICFR-01 | System shall support design and operating effectiveness testing of financial controls | High |
| FR-ICFR-02 | System shall attach sample testing evidence and track exceptions | High |
| FR-ICFR-03 | System shall generate deficiency reports | High |
| FR-ICFR-04 | System shall segregate management assessment vs auditor assessment | High |
| FR-ICFR-05 | System shall export ICFR Summary Report for external audit coordination | High |

---

### 3.14 Integration Module

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-INT-01 | System shall provide REST API endpoints | Critical |
| FR-INT-02 | System shall integrate with ERP systems (SAP, Oracle, Dynamics) | Medium |
| FR-INT-03 | System shall integrate with HR for employee data | Medium |
| FR-INT-04 | System shall export to Power BI / Excel | High |
| FR-INT-05 | System shall support SSO integration | High |

---

### 3.15 Notifications & Alerts

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-NOT-01 | System shall send email notifications | High |
| FR-NOT-02 | System shall display in-app alerts | High |
| FR-NOT-03 | System shall support reminder scheduling | High |
| FR-NOT-04 | System shall support configurable escalation matrix | Medium |

---

### 3.16 Audit Trail & Logging

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-LOG-01 | System shall log every critical action | Critical |
| FR-LOG-02 | System shall store logs immutably | Critical |
| FR-LOG-03 | System shall allow admin search of logs | High |
| FR-LOG-04 | System shall allow export of audit logs | High |
| FR-LOG-05 | System shall retain audit trail for ≥ 7 years | Critical |

---

## 4. Non-Functional Requirements

### 4.1 Security
- AES-256 encryption at rest
- SSL/TLS encryption in transit
- Multi-Factor Authentication support
- Immutable audit logs
- Role-based access control
- ISO 27001 alignment
- Periodic penetration testing

### 4.2 Performance
- Dashboard load time < 3 seconds
- Query response time < 2–3 seconds
- Support up to 500 concurrent users
- File upload support up to 100 MB

### 4.3 Availability
- Uptime ≥ 99.5%
- RPO = 24 hours
- RTO = 4 hours

### 4.4 Usability
- Intuitive UI
- Role-specific dashboards
- Contextual help tooltips
- Multi-language support (English, Arabic)

### 4.5 Backup & Recovery
- Automated daily backups
- Encrypted backup storage
- Disaster recovery plan
- Restoration testing twice annually

---

## 5. Data Model (High-Level Entities)

| Entity | Key Attributes |
|--------|-----------------|
| User | id, name, email, role, department, status |
| Role | id, name, permissions[] |
| Audit Universe | id, name, department, metadata, riskRating |
| Risk | id, entityId, factors, score, version |
| Audit Plan | id, year, entities[], status, version |
| Engagement | id, planId, objectives, scope, team, status, timeline |
| Working Paper | id, engagementId, file, version, signOff |
| Finding | id, engagementId, title, severity, owner, dueDate, status |
| Action Plan (CAP) | id, findingId, owner, dueDate, status, progress |
| Follow-up | id, actionPlanId, status, evidence |
| Activity | id, user, action, target, timestamp, type |
| QAIP Record | id, type, date, result |
| CSA Record | id, entityId, questionnaireId, responses, score |

---

## 6. Workflow Overview

```
Define Audit Universe → Risk Assessment → Audit Plan → Approval (Manager→CAE→Board) 
  → Execute Audit → Working Papers → Findings → MAPs → Follow-up → Closure → Close Audit
```

---

## 7. Implementation Phases (Suggested)

### Phase 1 – Foundation (Weeks 1–2)
- Database schema design and migrations
- Authentication (JWT, RBAC, MFA)
- User and role management
- Project setup (backend, frontend, devops)

### Phase 2 – Core Modules (Weeks 3–8)
- Audit Universe & Risk Assessment
- Annual Audit Planning
- Engagement Management
- Working Papers Repository
- Findings & Action Tracking
- Connect frontend to backend APIs

### Phase 3 – Risk & Analytics (Weeks 9–10)
- CSA
- ICFR
- Risk mappings
- Dashboard backend
- Reporting backend

### Phase 4 – Integration & Polish (Weeks 11–12)
- SSO integration
- ERP/HR integrations (optional)
- Notifications
- QA, testing, deployment, training

---

## 8. Technology Stack (from Proposal)

| Layer | Technology |
|-------|------------|
| Backend | Python (Django REST Framework) |
| Frontend | React (TypeScript) — existing |
| Database | PostgreSQL |
| Auth | JWT + MFA + SSO |
| Storage | S3-compatible (cloud or on-prem) |
| Deployment | Docker, Nginx, CI/CD |

---

## 9. Out of Scope (Initial Phase)

- External audit management
- Full GRC-wide compliance automation
- Advanced AI / continuous auditing
- Mobile application
- Board portal integration
- Legacy data migration (unless separately requested)

---

## 10. Traceability Matrix (Frontend vs Requirements)

| Module | FR Count | Frontend Status | Backend Status |
|--------|----------|-----------------|----------------|
| User & Access | 9 | Partial (Settings UI) | Not started |
| Audit Universe | 6 | ✅ Implemented | Not started |
| Risk Assessment | 10 | Partial (display) | Not started |
| Audit Planning | 9 | ✅ Implemented | Not started |
| Engagement | 10 | ✅ Implemented | Not started |
| Working Papers | 9 | ❌ Not started | Not started |
| Findings | 10 | ✅ Implemented | Not started |
| CAPs | 8 | ✅ Implemented | Not started |
| Dashboard | 11 | ✅ Implemented | Not started |
| Reports | 7 | Templates only | Not started |
| QAIP | 6 | ❌ Not started | Not started |
| CSA | 5 | ❌ Not started | Not started |
| ICFR | 5 | ❌ Not started | Not started |
| Integration | 5 | ❌ Not started | Not started |
| Notifications | 4 | UI only | Not started |
| Audit Trail | 5 | ❌ Not started | Not started |

---

*Document Version: 1.0*  
*Last Updated: February 2026*  
*Source: Audit.txt, IAMS Design Document.txt, Proposal.txt, Requirements.txt, System Features.txt, iams-frontend codebase*
