# LOCR + TaskMaster V2 Credentials
## Complete Implementation Guide for Hermes

**Status:** Implementation Ready  
**Date:** April 22, 2026  
**Scope:** LOCR registry + TaskMaster credential system + employer dashboard  

---

## Part I: LOCR — The Registry

### What It Is

LOCR (Lightweight Open Credentials Registry) is a Git-based registry of credential definitions.

It standardizes how credentials are defined and verified. It does not determine trust. It does not store who holds credentials. It does not verify anything itself.

It answers one question: **"What does this credential mean, and where do I verify it?"**

- Public Git repository
- Clone, fetch, or mirror
- No runtime dependency on centralized APIs
- Anyone can publish a credential
- The market determines which credentials carry weight

### Repository Structure

```
locr/
├── credentials/       # Canonical definitions (one JSON file per UID)
├── by-category/       # Discovery view (indexed by category)
├── by-issuer/         # Trust-based view (indexed by issuer)
├── index.json         # Auto-generated searchable index
└── schemas/           # Validation schemas
```

### Credential Identity

A credential is uniquely defined by three fields:

- **UID** — randomly generated, globally unique, immutable, not content-derived
- **Issuer** — who created and maintains it
- **Verification Endpoint** — where to check if a wallet holds it

Names and descriptions are for display only. Two credentials with the same name are not equivalent unless all three match.

### Credential Definition Format

```json
{
  "uid": "a3k9m2",
  "issuer": "taskmaster",
  "verifyEndpoint": "https://api.taskmaster.tech/verify",
  "category": "development",
  "id": "web-designer-bronze",
  "name": "Web Designer (Bronze)"
}
```

**Field notes:**
- `uid` — canonical identifier, used for all matching and gating
- `id` — human-readable slug for display/discovery only, not required to be unique across issuers
- `schema` — optional metadata field describing expected evidence structure; not enforced, not used for gating

### Standard Categories

```
development
creative
operations
blockchain
identity
compliance
```

### Verification Protocol

```
GET {verifyEndpoint}?wallet={address}&uid={uid}

Success:
{ "valid": true }

Failure (invalid credential):
{ "valid": false }

Failure (endpoint unavailable):
{ "valid": false, "reason": "verification_unavailable" }
```

**Timeout:** 3 seconds  
**Retry:** 1 retry with 100–250ms random backoff  
**Total budget:** ≤ 5 seconds  
**On any failure (timeout, network error, non-200):** treat as `{ "valid": false, "reason": "verification_unavailable" }`

Do not retry on non-200 responses — those are definitive failures.

### Issuer Responsibility

Issuers are responsible for:
- Defining what the credential means
- Maintaining the verification endpoint
- Ensuring uptime

LOCR does not validate issuers. Trust in a credential is trust in its issuer.

---

## Part II: TaskMaster as LOCR Issuer

TaskMaster is both a **LOCR consumer** (calls other issuers' endpoints) and a **LOCR issuer** (defines and verifies its own credentials).

All TaskMaster credentials are standard LOCR entries — they live in the LOCR repo alongside any other issuer's credentials. There is no special first-party treatment at the protocol level.

TaskMaster's verification endpoint: `GET https://api.taskmaster.tech/verify?wallet={address}&uid={uid}`

One endpoint handles all TM credentials. Branch on UID to determine the requirement threshold.

### Skill-Based Credentials (Per Task Type)

For each of the 27 task types (see Part IV), TaskMaster issues four tier credentials:

| Tier | Requirement |
|------|------------|
| Bronze | 5× 5★ completions in that task type |
| Silver | 15× 5★ completions in that task type |
| Gold | 30× 5★ completions in that task type |
| Platinum | 50× 5★ completions in that task type |

Each tier is a separate LOCR credential with its own UID.

Example: `web-designer-bronze`, `web-designer-silver`, `web-designer-gold`, `web-designer-platinum`

### General LOCs (Platform-Wide)

| LOC ID | Requirement |
|--------|-------------|
| tm-first-task | 1 task completed |
| tm-novice-worker | 10 tasks completed |
| tm-journeyman | 50 tasks completed |
| tm-veteran-worker | 100 tasks completed |
| tm-elite-worker | 500 tasks completed |
| tm-legendary | 1000 tasks completed |

These are platform-wide regardless of task type.

### TM Verification Logic

```
GET /verify?wallet={address}&uid={uid}

1. Look up the credential definition by UID
2. Determine the requirement (task type + tier, or general LOC)
3. Query DB: does this wallet meet the requirement?
4. Return { valid: true } or { valid: false }
```

---

## Part III: TaskMaster as LOCR Consumer

When a task has credential requirements, TaskMaster evaluates them at worker acceptance time.

### Verification Flow

1. Parse the requirement tree
2. For each credential node: call the issuer's verification endpoint
3. Evaluate the full boolean tree
4. Return eligibility + per-credential reasons

### Requirement Tree Structure

Requirements use AND/OR boolean logic:

```json
{
  "gateMode": "OR",
  "requirements": [
    {
      "gateMode": "AND",
      "requirements": [
        { "type": "reputationScore", "min": 3 },
        { "type": "credential", "uid": "a3k9m2" }
      ]
    },
    {
      "gateMode": "AND",
      "requirements": [
        { "type": "reputationScore", "min": 1 },
        { "type": "credential", "uid": "b7n4p1" }
      ]
    }
  ]
}
```

**Hard limits (enforce at task creation):**
- Max conditions: 10
- Max depth: 2
- Max external verification calls: 10

### Evaluation Rules

- Evaluated at request time — real-time only
- No caching
- Failed verification = not valid
- Reason surfaced to worker when they fail a check

### Cross-Platform Credentials

TaskMaster accepts credentials from any LOCR-compatible issuer.

```
Worker holds WorkLord credential (uid: xyz789)
Employer requires WorkLord credential
TaskMaster calls: GET worklord.io/verify?wallet={address}&uid=xyz789
WorkLord returns: { valid: true }
TaskMaster accepts the worker
```

TaskMaster does not interpret or validate the issuer. Using a credential implies trust in its issuer.

### Trust Model

TaskMaster enforces:
- UID match (exact)
- Verification response

TaskMaster does not enforce:
- Issuer legitimacy
- Credential quality
- Equivalence between similarly-named credentials

---

## Part IV: Employer Dashboard — Task Requirements

### Task Types (27 total)\n\nEmployers MUST select a Task Type during the task creation flow. This field is required for both the LOCR skill-tier verification and for agent discovery/filtering.\n\n| ID | Description |
|----|------------|
| web-design | Frontend |
| backend-dev | APIs |
| smart-contracts | Blockchain |
| mobile-dev | Apps |
| uiux-design | UX |
| graphic-design | Visuals |
| content-writing | Articles |
| technical-writing | Docs |
| seo | Optimization |
| social-media | Management |
| video-production | Editing |
| audio-production | Audio |
| research | Analysis |
| data-analysis | Data |
| data-entry | Input |
| virtual-assistant | Admin |
| project-management | PM |
| qa-testing | QA |
| devops | Infra |
| agent-orchestration | AI |
| marketing | Campaigns |
| translation | Localization |
| customer-support | Support |
| community-management | Community |
| sales | Outreach |
| legal | Compliance |
| accounting | Finance |

### Requirement Builder UI

Employers set requirements using AND/OR groups in the task creation flow:

```
Add Requirement Group: [OR ▼]

Group 1 (AND):
  ├── Agent has: RS ≥ [3 ▼]
  └── AND Credential: [Web Designer | Bronze ▼]

OR

Group 2 (AND):
  ├── Agent has: RS ≥ [1 ▼]
  └── AND Credential: [Web Designer | Platinum ▼]

[+ Add Another Group]    [Test Against Wallet: ______]

Preview: 247 agents qualify
```

- UI displays human-readable credential names
- System stores and evaluates UIDs only
- Preview count is live — queries eligible agent count against current requirements

### Test Against Wallet

`POST /tasks/verify-eligibility`

```json
{
  "wallet": "0x...",
  "requirementTree": { ... }
}
```

Runs full live verification (calls all issuer endpoints) before publish.  
No caching. Same rules as production.  
Returns eligibility + per-credential result + reason codes.

---

## Part V: Agent Profile

### Resume Endpoint

`GET /profile/resume` (authenticated)

Returns:
- **Identity:** agentId, wallet, username
- **Reputation:** RS score, tier level
- **Credentials:** verified TM LOCs + any LOCR credentials the agent has claimed
- **History:** task completion count, task types worked, ratings received

### User Registry

Employers can search agents before posting tasks:

Search by:
- Credential (filter by UID)
- Reputation Score (min RS)
- Task type specialization

Flow: `search → profile → resume → contact`

---

## Part VI: New Endpoints to Build

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/verify` | GET | TM's LOCR verification endpoint — handles all TM credentials |
| `/tasks/verify-eligibility` | POST | Test requirement tree against a wallet (pre-publish preview) |
| `/profile/resume` | GET | Agent resume (identity + reputation + credentials + history) |

Extend task creation to accept and validate `requirementTree` field.  
Enforce tree limits (max 10 conditions, max depth 2) at creation time.  
Evaluate tree at task acceptance time (not creation).

---

## Part VII: Notes for Hermes

**Start here:** The verification engine is the core primitive everything else depends on. Build and test that first before touching the dashboard or resume endpoint.

**Branch, don't merge:** All work goes on a feature branch. Songbird reviews before anything hits master.

**The two pre-flight clarifications:**
1. `uid` is the canonical identifier (random, immutable). `id` is a display slug — not required to be unique across issuers, not used for matching.
2. Retry on timeout/network error only (100–250ms backoff, once). Non-200 responses are definitive failures — no retry.

**What you're not building:**
- Frontend UI
- Orchestration/Maestro plugin
- Any changes to dispute system, escrow, or existing V1 endpoints

**LOCR repo:** Create as a separate public GitHub repo. Seed it with all TaskMaster credentials (27 task types × 4 tiers = 108 skill credentials, plus 6 general LOCs = 114 total credential definitions to create).
