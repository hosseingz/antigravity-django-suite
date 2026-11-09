# NOTICE — upstream attribution

This role layer is **adapted from the agent-persona pattern** of
[`msitarzewski/agency-agents`](https://github.com/msitarzewski/agency-agents).

- Upstream repository: `https://github.com/msitarzewski/agency-agents`
- Pinned commit: `8ae6164602c95ca78828b148b9052460ee426885` (2026-11-09)
- Upstream license: MIT
- Upstream copyright notice: `Copyright (c) 2025 AgentLand Contributors`

## What was adapted

Only structural ideas were taken, from these upstream surfaces:

| Upstream surface | Idea reused here |
|---|---|
| `engineering/engineering-backend-architect.md` (read in full) | Agent anatomy: identity, mission, critical rules, deliverables, communication, success metrics |
| `README.md` roster and `divisions.json` concept | Roster-as-data (`roles/registry.json`, `workflows/rosters.json`) |
| `integrations/antigravity/README.md` | Antigravity frontmatter convention (`name`, `description`, `risk`, `source`, `date_added`) and the `agency-` prefix convention that this layer deliberately avoids |
| `scripts/convert.sh` / `install.sh` behavior | Install/uninstall with explicit targeting, dry-run, and selective install — reimplemented here for PowerShell and for ownership safety |

## What was NOT taken

- No upstream prose, persona text, examples, or agent bodies were copied. Every role in `roles/` is original text written for the Django + DRF + Next.js + Docker stack of this suite.
- No upstream files are vendored into this repository. There is no submodule and no sync script.
- Upstream's installer is not used, and no upstream-generated files are written by this suite.

## MIT license text (upstream)

The upstream work is distributed under the MIT License; the notice required by that license is reproduced here for the adapted portions:

```
MIT License

Copyright (c) 2025 AgentLand Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
