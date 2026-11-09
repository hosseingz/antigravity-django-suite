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

## 2. Activation protocol

- Activate roles by **exact name** (`suite-auth-security-reviewer`). Do not invent aliases.
- One role per phase. If a task spans scopes, run **sequential passes**, not one merged persona.
- A role may edit only files inside the scope declared in [`roles/registry.json`](../../roles/registry.json). Cross-scope edits require a handoff.
- The roster for each workflow is data, not memory: read [`workflows/rosters.json`](../../workflows/rosters.json) before starting.

## 3. Handoff protocol

A handoff is complete only when it carries:

1. **State** — what was decided/changed, in one or two sentences.
2. **Evidence** — the command and its output, or the file and line, that proves it.
3. **Open risks** — what the next role must not assume.
4. **Next role** — named explicitly from the current role's `## Handoff` section.

Never hand off with "looks good" or with a summary that omits the failing checks.

## 4. Conflict resolution

- Guardrail vs role: guardrail wins, always.
- Two roles disagree: the disagreement is written down (asset, option A, option B, recommendation) and escalated to `suite-qa-release-gate`, which arbitrates on evidence — then a decision record is added to the target project's `DECISIONS.md` with a date.
- Role vs skill: the skill describes the house pattern; deviation needs a decision record, not a preference.
- Anything security-critical is resolved in favor of the stricter option until a human explicitly approves otherwise.

## 5. Non-negotiable limits on any persona

A role **must not**:

- disable, skip, weaken, or "temporarily" bypass a guardrail;
- remove or relax a test to make a change pass;
- bypass `suite-qa-release-gate` before declaring work done;
- introduce a second architecture, HTTP client, cache layer, state library, or auth scheme that the suite already owns;
- claim a verification that was not executed in this session.

## 6. Installation boundary

The role installer (`scripts/install-roles.ps1`) writes only `<project>/.agents/agents/suite-*.md` and its ownership file `.agents/suite-install-state.json`. It must never write `.agent/`, `.agents/skills/`, `.agents/rules/`, or `.agents/workflows/`, and it must never overwrite a file it does not own.

> Compatibility note: this file lives in the legacy `.agent/rules/` directory, matching the rest of the suite. If the guardrail set is migrated to the canonical `.agents/rules/` layout, every rule file — including this one — needs activation frontmatter (`trigger: always_on`), otherwise Antigravity will not load it.
