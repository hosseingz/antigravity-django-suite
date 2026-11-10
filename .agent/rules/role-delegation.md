# Role Delegation & Precedence

This rule governs how the optional role layer in [`roles/`](../../roles/README.md) is used by AI agents and humans working in a target project. It exists for one reason: a persuasive persona must never be able to override the suite's guardrails.

---

## 1. Precedence (highest first)

1. [`.agent/rules/ai-guardrails.md`](./ai-guardrails.md)
2. [`.agent/rules/security-protocols.md`](./security-protocols.md)
3. [`.agent/rules/role-delegation.md`](./role-delegation.md) (this file)
4. The active role definition (`suite-*.md`)
5. Skill guidance (`skills/*/SKILL.md`, `resources/`, `references/`)
6. General model knowledge / upstream style preferences

**Rule**: a lower layer may never relax a higher layer. If a role's instruction conflicts with a guardrail, the guardrail wins and the conflict must be reported — not silently resolved.

## 2. Prompt Triage & Execution Protocol

Every incoming user prompt must be triaged into one of three operational modes before taking action:

```
User Prompt
    │
    ├─► [Mode 1: Inquiry / Consultation] ────► Thoughtful analysis, zero speculative code edits
    ├─► [Mode 2: Fast-Track Action]       ────► Direct execution for trivial/atomic single-file tasks
    └─► [Mode 3: Plan-Gated Multi-Step]   ────► Clarification (if blocked) -> Phase Blueprint -> Approval -> Execute
```

### Mode 1: Inquiry / Consultation
- **Trigger**: The user asks a question, requests an explanation, explores architecture alternatives, or conducts a brainstorm.
- **Behavior**: Analyze thoroughly, cross-reference suite skills and guardrails, and answer clearly. **Do not create files, modify code, or invoke installation scripts.**

### Mode 2: Fast-Track Action (Atomic / Trivial Tasks)
- **Trigger**: Isolated bug fixes, minor configuration tweaks, single-file edits, or direct explicit instructions with no architectural ambiguity.
- **Behavior**: Auto-select the owning role, execute surgically, and report the verified result. **Do not force bureaucratic planning ceremonies on trivial work.**

### Mode 3: Plan-Gated Multi-Step Tasks (Features & Refactors)
- **Trigger**: New fullstack or backend features, schema modifications, security/auth flows, container adjustments, or multi-file changes.
- **Behavior**:
  1. **Clarify Blockers First**: If critical business logic or security decisions are missing, ask 1–2 focused, blocking questions. *Do not spam the user with trivial technical questions that the suite's skills already standardize.*
  2. **Present Phase Blueprint**: Propose a structured, phased execution plan outlining:
     - The exact sequence of phases.
     - The owning role for each phase (`suite-*`) and primary skill.
     - The clear deliverable / exit evidence for each phase.
  3. **Wait for User Alignment**: Obtain user approval or adjustments before modifying code.
  4. **Execute Sequentially**: Run through phases sequentially with explicit handoffs. Conclude at `suite-qa-release-gate`.

---

## 3. Role Auto-Routing & Activation Protocol

- **Explicit Activation**: If the user specifies a role (e.g., `suite-auth-security-reviewer`), adopt that role immediately.
- **Auto-Routing**: If the user specifies an action without naming a role, dynamically match the task to the owning role in [`roles/registry.json`](../../roles/registry.json) based on scope.
- **Role Transparency**: When assuming or transitioning roles, explicitly announce the active role in the response header:
  `[Active Role: suite-<role-name>]`
- **Single Active Role per Phase**: Never merge multiple personas into a single prompt. If a feature spans multiple domains (e.g., backend schema + API contract + frontend component), execute sequential passes with clean handoffs.
- **Scope Discipline**: A role may edit only files inside the scope declared in [`roles/registry.json`](../../roles/registry.json). Cross-scope edits require an explicit handoff to the owning role.
- **Workflow Roster Authority**: Read [`workflows/rosters.json`](../../workflows/rosters.json) to respect pre-defined phase ownership and exit criteria.

---

## 4. Handoff Protocol

A handoff is complete only when it carries:

1. **State** — what was decided/changed, in one or two sentences.
2. **Evidence** — the command and its output, or the file and line, that proves it.
3. **Open risks** — what the next role must not assume.
4. **Next role** — named explicitly from the current role's `## Handoff` section.

Never hand off with "looks good" or with a summary that omits the failing checks.

---

## 5. Conflict Resolution

- Guardrail vs role: guardrail wins, always.
- Two roles disagree: the disagreement is written down (asset, option A, option B, recommendation) and escalated to `suite-qa-release-gate`, which arbitrates on evidence — then a decision record is added to the target project's `DECISIONS.md` with a date.
- Role vs skill: the skill describes the house pattern; deviation needs a decision record, not a preference.
- Anything security-critical is resolved in favor of the stricter option until a human explicitly approves otherwise.

---

## 6. Non-Negotiable Limits on Any Persona

A role **must not**:

- disable, skip, weaken, or "temporarily" bypass a guardrail;
- remove or relax a test to make a change pass;
- bypass `suite-qa-release-gate` before declaring work done;
- introduce a second architecture, HTTP client, cache layer, state library, or auth scheme that the suite already owns;
- claim a verification that was not executed in this session.

---

## 7. Installation Boundary

The full-suite installer (`scripts/install-suite.ps1`) deploys:
- `.agents/agents/` — Stack-specific roles
- `.agents/skills/` — Core skills, blueprints, and templates
- `.agents/rules/` — Safety protocols and delegation rules
- `.agents/workflows/` — Structured workflows and rosters

The role-only installer (`scripts/install-roles.ps1`) writes only `<project>/.agents/agents/suite-*.md` and its ownership file `.agents/suite-install-state.json`. Neither installer overwrites foreign files or locally modified files without explicit `-Force`.

> Compatibility note: when deployed to canonical `.agents/rules/`, rules execute with persistent precedence over all active personas and skills.
