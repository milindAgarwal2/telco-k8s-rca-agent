# AIDE action first responses

This MIT-licensed community skill is bundled only by the `full` / `all`
installation flavor. The installer copies this folder to the target project's
`.kiro/skills/aide-action-first-responses/`. It adds no runtime dependencies and requires no
MCP service or credential.

This professionally named adaptation derives from upstream revision
`0a84de401019a3a822248df586d88a2b56f8c6af`:
[upstream skill](https://github.com/ayghri/i-have-adhd/blob/0a84de401019a3a822248df586d88a2b56f8c6af/skills/i-have-adhd/SKILL.md).
The bundled LICENSE retains the original copyright and permission notice;
source-info.json retains the original source paths and hashes and records
the adapted bundled-file hashes. The name, display metadata, activation
phrase and introductory wording are adapted to a generic professional style.

## Use in Kiro

Start a new conversation in the installed project and invoke:

    /aide-action-first-responses

The requested presentation leads with an action, numbers multi-step work,
keeps relevant state visible, and makes completed work clear. Turn it off
by sending `stop action first mode` or `normal mode`. Activation requests a
format preference; installation alone does not request this mode.

Kiro documents workspace skill discovery and slash invocation in its
[skills guide](https://kiro.dev/docs/skills/). AIDE full custom agents already
reference the workspace skill catalog through their skill resources. If an
older client does not expose the slash command, explicitly ask it to read
`.kiro/skills/aide-action-first-responses/SKILL.md` and use that presentation for the session.

The upstream `disable-model-invocation: true` field is retained. Its enforcement
depends on the client; the cited Kiro frontmatter documentation does not list
that field. Explicit opt-in should be verified with the smoke test below.

This is an on-demand response skill, not always-included steering. Its
explicitly requested presentation takes precedence over the optional BOS AIDE
banner and layout. Repository safety rules, task requirements, tool approval,
and accurate evidence remain applicable. The adapted agents/ files are
metadata for other clients; AIDE does not install them into global settings.

## Read-only client smoke test

1. Before invoking the skill, ask for a short explanation and confirm the
   response mode has not been activated by installation alone.
2. Invoke `/aide-action-first-responses`, then ask for a three-step read-only repository
   orientation. Confirm Kiro loads the skill and leads with a concrete action.
3. Ask a follow-up and confirm the chosen format and relevant state persist.
4. Send `stop action first mode`; confirm normal presentation resumes.
5. Repeat in Kiro IDE and CLI, including an AIDE full custom agent.

Automated installer checks verify full-only delivery, matching bundled
contents, idempotency, and removal on downgrade. Live Kiro activation,
frontmatter enforcement, and persistence remain unverified until this client
smoke test is performed.
