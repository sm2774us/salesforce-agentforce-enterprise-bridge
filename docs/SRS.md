# Software Requirements Specification (IEEE 830-style)
**Product:** Agentforce Enterprise Bridge  **Version:** 1.0  **Status:** Approved for MVP

## 1. Introduction
**Purpose:** specify a governed integration that lets Agentforce-style agents act on enterprise telemetry safely. **Scope:** ingestion, grounding, planning, governed action, audit. **Out of scope:** UI console, production Kafka, Data Cloud licensing.

## 2. How requirements were gathered (illustrative engagement)
Personas below model a typical discovery; replace with real names/outcomes when presenting a real engagement.

| Stakeholder | Ask (verbatim style) | Classification | Resolution |
|---|---|---|---|
| Business sponsor (COO) | "AI that resolves disputes automatically." | **Ambiguity** — what is "resolve", which decisions? | Decision-classification workshop → autonomy tiers (FR-5, FR-6) |
| Compliance lead | "Nothing financial without a human; prove it." | Clear constraint | HITL gate + audit (FR-6, FR-8) |
| CRM admin | "Don't break our org; no new licences." | Constraint | Free-tier objects, permission set, SFDX (FR-9, C-2) |
| Customer architect | "Will it survive upstream schema changes and 429s?" | **Uncertainty** — measurable by spike | Contract + DLQ, breaker/backoff spike (FR-2, NFR-2) |
| Security | "No PII to models or CRM; least privilege." | Clear constraint | PII redaction, RBAC (FR-4, FR-7) |

*Ambiguity* = the requirement is unclear and is resolved by asking people. *Uncertainty* = the answer is unknown and is resolved by experiments/measurement.

## 3. Functional requirements
| ID | Requirement | Verified by |
|---|---|---|
| FR-1 | Accept telemetry via `POST /v1/events`; sync (`wait=true`) and async modes | `test_api_end_to_end` |
| FR-2 | Reject payloads violating the versioned schema; retain in DLQ | `test_bus_flow` |
| FR-3 | Idempotent ingest by `event_id`; 429 when saturated | `test_bus_flow`, `test_backpressure_429` |
| FR-4 | Redact SSN, card (Luhn), email, phone before prompts/audit/CRM | `test_redact*`, `test_pii_redacted_before_audit` |
| FR-5 | Resolve account name variants to one entity; scope context per account | `test_grounding_*` |
| FR-6 | Risk-tiered actions; HIGH requires approval by a different human, with TTL | `test_hitl_*`, `test_approval_store_ttl` |
| FR-7 | RBAC: VIEWER/AGENT/APPROVER/ADMIN; fail-closed auth | `test_rbac`, `test_api_end_to_end` |
| FR-8 | Audit every decision locally and in `Bridge_Audit_Log__c`; retry on outage | `test_audit_outbox` |
| FR-9 | Create/escalate Cases via Salesforce REST using OAuth 2.0 | `test_salesforce.py` |
| FR-10 | Expose action catalog/OpenAPI for Agentforce External Services | `test_registry` |
| FR-11 | LLM planner optional; degrade to rules on any failure | `test_resilient_planner` |

## 4. Non-functional requirements
| ID | Requirement | Verification |
|---|---|---|
| NFR-1 | Offline p95 pipeline latency < 5 ms; ≥1k events/s/core | `bridge bench` |
| NFR-2 | Survive 429/5xx/network/401 with bounded retries; breaker prevents cascade | `test_retries_*`, `test_circuit_opens` |
| NFR-3 | Memory bounded (queue, dedupe, history, DLQ, audit, approvals) | design + unit tests |
| NFR-4 | No secrets in repo; masked in logs/repr | `test_settings_env`, `.env.example` |
| NFR-5 | 100% line+branch coverage; Google style; CI matrix 3.11–3.13 | CI |
| NFR-6 | Health/readiness/metrics endpoints | `test_api_*` |

## 5. Constraints & assumptions
C-1 Python ≥3.11. C-2 Free Developer Org; client-credentials flow needs My Domain URL. C-3 Single replica for MVP (in-memory approvals). A-1 Upstream sends UTC timestamps.

## 6. Acceptance criteria
Demo shows: PII stripped, "ACME Corp." merged with "Acme Corporation", low-risk Case auto-created, $25k review held until a different human approves, audit rows for all, CI green at 100%.
