# Role Layer — adopting the agency-agents pattern without collisions

This directory adapts the **agent-persona pattern** of [`msitarzewski/agency-agents`](https://github.com/msitarzewski/agency-agents) (MIT) into a small, stack-specific roster for this suite. It is a **role layer**, not a second skill library: skills still hold the "how" for Django/DRF/Next.js; roles hold the "who reviews what, and when is it done".

Upstream relationship, in plain terms:

- We borrowed **structure and process discipline** (role anatomy, handoff, success metrics, roster-as-data, definition of done).
- We did **not** vendor upstream content. No upstream prose is copied; every role below was written for this stack, referencing this repository's skills.
- We did **not** run upstream's installer, and nothing here writes into `.agent/` or `.agents/skills/`.

---

## 1. What is in here

| Path | Purpose |
|---|---|
| `roles/suite-*.md` | Seven installable role definitions (`suite-` prefix, namespaced on purpose) |
| `roles/registry.json` | Machine-readable roster: role → scope, skills, workflows, risk, handoff |
| `roles/NOTICE.md` | MIT attribution and the pinned upstream commit |
| `workflows/rosters.json` | Per-workflow phase → owning role → exit evidence |
| `.agent/rules/role-delegation.md` | Precedence rule: personas can never override the guardrails |
| `scripts/install-roles.ps1` | Ownership-safe installer (dry-run, list, selective, uninstall) |

Roles are **not** skills. They are not auto-discovered from this repository, and they do not compete with the five skills for the skill inventory.

## 2. The roster

| Role | Owns | Primary skills | Typical workflow phase |
|---|---|---|---|
| [`suite-backend-architect`](./suite-backend-architect.md) | App boundaries, config/, schema, migrations | `django-core-architecture` | Scaffold → backend core |
| [`suite-api-contract-reviewer`](./suite-api-contract-reviewer.md) | Endpoint inventory, SSR/CSR data path, error shape | `nextjs-api-sync` | Scaffold → API sync |
| [`suite-auth-security-reviewer`](./suite-auth-security-reviewer.md) | Cookie lifecycle, OTP, permissions, secrets | `auth-jwt-cookie-session` | Auth setup, every security-touching change |
| [`suite-data-cache-engineer`](./suite-data-cache-engineer.md) | Redis cart atomicity, guest merge, indexes | `domain-ecommerce-cart` | Cart enablement, concurrency changes |
| [`suite-frontend-integrator`](./suite-frontend-integrator.md) | RSC/client boundary, stores, async UI states | `nextjs-api-sync`, cart/auth stores | Any UI feature |
| [`suite-devops-platform`](./suite-devops-platform.md) | Docker/compose/nginx/celery, secrets, healthchecks | `django-docker-scaffold` | Scaffold → infrastructure |
| [`suite-qa-release-gate`](./suite-qa-release-gate.md) | Definition of done, evidence, veto | all | End of every workflow, before merge/release |

## 3. Installing into a target project

Roles and Skills live in this repository as source; they are installed into **your application repository**, because that is where the agent works.

### Full Suite (Roles + Skills + Rules + Workflows - Recommended)
To install the entire suite so all skills, blueprints, and guardrails are in place:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-suite.ps1 -Target C:\src\myapp
```

### Roles Only
To install only the role definitions (into `<project>/.agents/agents/*.md`):
```powershell
# preview (no writes)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp -DryRun

# install all seven roles
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp

# install only what the current phase needs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp -Only suite-auth-security-reviewer,suite-qa-release-gate

# inspect / remove
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp -List
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp -Uninstall
```

> **Execution policy:** on machines where script execution is disabled (`... running scripts is disabled on this system`), invoke the installer through a bypassed child process instead of calling the file directly:
> `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-roles.ps1 -Target C:\src\myapp -DryRun`

Manual fallback (no script): copy `roles/suite-*.md` into `<project>/.agents/agents/`. Keep the `suite-` prefix — it is what makes conflicts detectable. On macOS/Linux, the equivalent one-liner is:

```bash
mkdir -p "$PROJECT/.agents/agents" && cp roles/suite-*.md "$PROJECT/.agents/agents/"
```

(The ownership file is only written by the PowerShell installer; a manual copy is simply not tracked for uninstall. A second, bash installer is intentionally not shipped, so there is exactly one install implementation to keep honest.)

### Why this cannot clash with your existing setup

| Collision surface | This layer's behavior |
|---|---|
| Folder | Installs only to `.agents/agents/`. Never writes `.agent/`, `.agents/skills/`, `.agents/rules/`, or `.agents/workflows/`. |
| Name | Every file is `suite-<role>.md`. Upstream's installed artifacts use `agency-<slug>`; the two prefixes cannot collide, and `-Only`/`-Uninstall` operate on exact names. |
| Skills inventory | Roles install no skills, so they never appear in the skill list or compete for activation. |
| Rules precedence | `.agent/rules/role-delegation.md` makes guardrails win over any role; every role file repeats that constraint inline. |
| Owned files | The installer records `sha256` in `.agents/suite-install-state.json` and refuses to overwrite foreign or locally modified files unless `-Force`. |
| Upstream drift | Roles are adapted, not synced. `roles/NOTICE.md` pins the upstream commit; re-read upstream deliberately, never automatically. |

> If you also want the upstream catalog, be intentional: run their installer with a filtered division (`engineering`, `testing`, `security`) and keep in mind it writes **skills**, while this layer writes **agents**. Do not point both at the same paths.

## 4. How to use them while coding

1. Pick the workflow (`workflows/01`, `02`, `03`) and open `workflows/rosters.json`.
2. Activate the role that owns the current phase, by exact name (e.g. "Use the suite-auth-security-reviewer role to review this change").
3. Require the role's deliverables before moving to the next phase; hand off with the role named in its `## Handoff` section.
4. Close the workflow with `suite-qa-release-gate`: no evidence, no "done".

Roles are intentionally narrow. If a task spans two roles, run them as two passes (one reviews, the other implements) instead of merging them into one broad prompt — that separation is the point.

## 5. Updating

- Upstream is pinned in `roles/NOTICE.md`. Treat role text as **this repository's code**: change it here, review it here, bump `roles/registry.json` version.
- Do not re-import upstream prose; if an upstream idea is worth adopting, rewrite it against the suite's skills and guardrails.
- If you change a role's name, update `registry.json`, `workflows/rosters.json`, and any `## Handoff` links in the same change.
