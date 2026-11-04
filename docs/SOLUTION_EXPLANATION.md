# Solution Explanation

## 1. Problem & approach
Enterprise signals (ERP, payments, telemetry) are fragmented; agents acting on them hallucinate, leak PII, and take irreversible actions without oversight. The bridge enforces: **ground first, plan second, govern every tool call, audit everything**.

## 2. System context
```mermaid
flowchart LR
  subgraph Enterprise
    ERP[ERP / Payments / Telemetry]
  end
  subgraph Bridge["Agentforce Enterprise Bridge (FastAPI)"]
    API[REST API + OpenAPI]
    BUS[Event Bus\ndedupe · DLQ · backpressure]
    GR[Grounding\nentity resolution · DMO · vectors]
    PL[Planner\nrules / LLM + fallback]
    CT[AI Control Tower\nRBAC · PII · risk gate · audit]
    AP[Approval Store]
  end
  subgraph SF[Salesforce Developer Org]
    CASE[Case]
    TEL[Telemetry_Event__c]
    AUD[Bridge_Audit_Log__c]
    AF[Agentforce Agent + External Service]
  end
  ERP -->|POST /v1/events| API --> BUS --> GR --> PL --> CT
  CT -->|low risk| CASE
  CT -->|high risk| AP -->|human approves| CASE
  GR --> TEL
  CT --> AUD
  AF -->|invoke action| API
```

## 3. Sequence — event to governed action
```mermaid
sequenceDiagram
  autonumber
  participant S as Source system
  participant A as API
  participant B as EventBus
  participant G as Grounding
  participant P as Planner
  participant T as ControlTower
  participant H as Human approver
  participant SF as Salesforce
  S->>A: POST /v1/events (X-API-Key)
  A->>B: publish_raw (validate, dedupe)
  alt schema drift
    B-->>A: SchemaDriftError (DLQ)
    A-->>S: 422
  else queue full
    A-->>S: 429 Retry-After
  else accepted
    A-->>S: 202
  end
  B->>G: ingest (resolve entity, redact PII)
  G->>SF: mirror Telemetry_Event__c (best effort)
  G->>P: UnifiedEvent + GroundedContext
  P->>T: ActionRequest
  T->>T: RBAC, redact, validate, risk tier
  alt LOW risk
    T->>SF: create Case (OAuth, retry, breaker)
    T->>SF: audit record
  else HIGH risk
    T->>SF: audit PENDING_APPROVAL
    H->>T: POST /v1/approvals/{id}/decision
    T->>T: separation-of-duties check
    T->>SF: create Case + audit EXECUTED
  end
```

## 4. Customer interaction (discovery → delivery)
```mermaid
sequenceDiagram
  participant Sp as Business sponsor
  participant FDE as FDE
  participant Ar as Customer architect
  participant Sec as Security/Compliance
  Sp->>FDE: "Resolve disputes automatically"
  FDE->>Sp: Workshop: classify decisions (ambiguity)
  FDE->>Ar: Spike: latency, schema drift (uncertainty)
  FDE->>Sec: Control requirements → Control Tower
  FDE->>Sp: MVP in days (offline demo, then live org)
  Sp->>FDE: Approve autonomy boundaries
  FDE->>Ar: Handover: ADRs, runbook, tests
```

## 5. Decision flow
```mermaid
flowchart TD
  E[Event] --> V{Valid schema?}
  V -- no --> D[DLQ + 422]
  V -- yes --> A{amount ≥ threshold?}
  A -- yes --> F[create_financial_review · HIGH]
  A -- no --> L{severity low?}
  L -- yes --> N[No action]
  L -- no --> C[create_case · LOW priority by severity/recurrence]
  F --> Q[Approval queue → human]
  C --> X[Execute + audit]
```

## 6. Approval state machine
```mermaid
stateDiagram-v2
  [*] --> Pending: HIGH-risk submit
  Pending --> Executed: approver ≠ requester approves
  Pending --> Rejected: approver rejects
  Pending --> Expired: TTL elapsed
  Pending --> Denied: wrong role / same person
  Executed --> [*]
  Rejected --> [*]
  Expired --> [*]
```

## 7. Data model
```mermaid
erDiagram
  ACCOUNT ||--o{ CASE : has
  ACCOUNT ||--o{ TELEMETRY_EVENT__c : "Account_Key__c"
  CASE ||--o{ BRIDGE_AUDIT_LOG__c : "Event_Id__c"
  TELEMETRY_EVENT__c { text Event_Id__c UK  text Severity__c  number Amount_Usd__c  longtext Message__c }
  BRIDGE_AUDIT_LOG__c { text Audit_Id__c UK  text Actor__c  text Action__c  text Decision__c  longtext Payload_Json__c }
```

## 8. Class overview
```mermaid
classDiagram
  class ControlTower { +submit() +decide() }
  class ActionRegistry { +register() +get() +manifest() }
  class SalesforceGateway { <<Protocol>> }
  class SalesforceClient
  class InMemorySalesforce
  class Planner { <<Protocol>> }
  class RuleBasedPlanner
  class AnthropicPlanner
  class ResilientPlanner
  SalesforceGateway <|.. SalesforceClient
  SalesforceGateway <|.. InMemorySalesforce
  Planner <|.. RuleBasedPlanner
  Planner <|.. AnthropicPlanner
  Planner <|.. ResilientPlanner
  ResilientPlanner o-- Planner
  ControlTower --> ActionRegistry
  ControlTower --> ApprovalStore
  ControlTower --> AuditLog
  ActionRegistry --> SalesforceGateway
```

## 9. Deployment
```mermaid
flowchart LR
  GH[GitHub Actions] -->|build/test 100%| IMG[GHCR image]
  GH -->|sf deploy| ORG[(Dev Org)]
  IMG --> K8s[Container · non-root · read-only]
  K8s -->|OAuth client credentials| ORG
  K8s --> PM[Prometheus /metrics]
  SEC[(GitHub Environment secrets)] --> GH
```

## 10. AI best practices implemented
| Practice | Where |
|---|---|
| Ground before generate; scope context per tenant | `grounding.py` (per-account index) |
| Untrusted-input framing & prompt-injection containment | `agent.py` system prompt; LLM output can only *propose* — Control Tower still enforces RBAC/HITL |
| Constrained, validated outputs | JSON-only, allow-listed actions, pydantic validation twice |
| Deterministic fallback / graceful degradation | `ResilientPlanner` + metric `planner_fallback` |
| PII minimisation before prompt, audit, CRM | `pii.py` at ingest and at tool call |
| Risk-tiered human-in-the-loop, separation of duties | `actions.RiskTier`, `ControlTower.decide` |
| Full auditability, tamper-evident-ish append log | `audit.py` → `Bridge_Audit_Log__c` |
| Evaluation as tests | planner policy tests, adversarial LLM-output tests |
| Observability | `/metrics`, decision counters, latency quantiles |

## 11. Resilience & performance
Backoff `U(0, min(5s, 0.2·2ⁿ))`; breaker opens after 5 consecutive 5xx/transport failures, half-opens after 30s; 401 → token refresh; 4xx not retried (and don't trip breaker). Bus is bounded (O(1) enqueue, 429 backpressure); dedupe and history are bounded LRU/FIFO (O(1)); vector recall is O(n log k) over ≤100 docs per account; approval store O(1) with lazy expiry. Measured offline (in-memory CRM, 1 core): ~2.5k events/s, p50 0.38 ms, p95 0.51 ms — this excludes real Salesforce network latency.

## 12. Security
Salesforce auth is key-based by default: an RS256 JWT assertion (180 s lifetime) signed with a private key that never leaves the host; only the certificate is uploaded to Salesforce (`jwt_auth.py`). Client-credentials remains a fallback.

Secrets only via env / GitHub Environment secrets; masked in `repr`; constant-time API-key compare; fail-closed auth; SOQL escaping + sObject/Id validation; least-privilege permission set; non-root read-only container; CodeQL + pip-audit.

## 13. How to improve
1. Replace `EventBus` internals with a Kafka consumer group (key by account for ordering; commit offsets after handling; DLQ topic).
2. Persist approvals + audit outbox in Postgres/Redis for HA and restarts; use Audit_Id__c upsert for exactly-once audit.
3. Real Data Cloud: Streaming Ingestion API / zero-copy federation from Snowflake/Databricks; Data Cloud vector search replaces `VectorIndex`.
4. Platform Events / Pub-Sub API for Salesforce→bridge callbacks; Flow-based approval in Salesforce.
5. LLM eval harness (golden set, LLM-as-judge, regression gate in CI), tracing (OpenTelemetry), per-tenant rate limits, OAuth/JWT inbound instead of API keys.
6. Single-probe half-open breaker; Retry-After awareness; React approver console.
