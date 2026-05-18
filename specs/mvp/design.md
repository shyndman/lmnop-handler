## Context

The current codebase is a hello-world FastMCP server with one demo tool and no Obsidian integration. The MVP replaces that placeholder surface with a real MCP server that runs on the same machine as the Obsidian desktop app and talks to the vault through the Obsidian CLI over IPC. The intended clients are hosted assistants such as Claude and ChatGPT, so the server must be publicly reachable and authenticated, but the workflow logic itself stays client-side. The server's job is to expose a minimal, task-oriented surface for recent review, note capture, and task resolution.

The real vault layout this MVP is designed around is:

```text
vault/
├── journal/
│   ├── 2026-05-16.md
│   └── 2026-05-17.md
└── notes/
    └── projects/
        ├── eavesdrop/
        │   └── .minutes.md
        └── voice-assistant/
            └── .minutes.md
```

Implementation must not hardcode `journal/`. It should derive the current daily-note folder from `obsidian daily:path`, because the local test fixture currently uses `tests/vault/handler-test-vault/journals/`. End-to-end tests must explicitly target that fixture vault rather than the active personal vault.

Dependency review against the current project state:

- Direct runtime dependency already declared: `fastmcp`
- Direct dev dependencies already declared: `pytest`, `basedpyright`
- No new runtime dependency is required for the MVP if implementation stays on FastMCP public APIs plus the Python standard library (`asyncio`, `hashlib`, `json`, `os`, `pathlib`, `secrets`)
- No new test dependency is required for the MVP; `pytest` plus local fixtures and monkeypatching are enough
- If implementation later chooses to import a package that is only present transitively, it must be added explicitly with `uv add <package>` or `uv add --dev <package>` rather than relying on FastMCP's dependency tree

## Goals / Non-Goals

**Goals:**
- Expose one MCP resource, `obsidian://daily-standup`, that gives the client the authoritative briefing required to conduct the daily standup conversation.
- Expose one content write path, `append`, that can capture one or more markdown list items into today's journal note or a project's `.minutes.md` note.
- Expose one task status write path, `resolve`, that can mark tasks done, dropped, or carried forward.
- Authenticate every MCP request with bearer tokens.
- Keep the vault clean by deriving task IDs from current vault data instead of writing metadata into task lines.
- Keep the server voice-friendly by making the MCP surface workflow-oriented rather than file- or note-oriented.
- Distinguish clearly between tasks that were authored on recent days and tasks that are scheduled for today, even when the same task appears in both sets.
- Document the exact FastMCP and Obsidian CLI APIs the implementation is expected to call so implementation can proceed without external research.

**Non-Goals:**
- General-purpose Obsidian CRUD over MCP.
- Server-side prompts, conversation scripts, or opinionated morning-review orchestration.
- Synchronous vault sync as part of `append` or `resolve`.
- Stable task identities across task text edits or file moves.
- Multi-user conflict management beyond last-write-wins.
- Adding libraries unless implementation proves the current direct dependencies are insufficient.

## Decisions

### 1. Stay on FastMCP + stdlib by default, but prefer a library over ad hoc complexity

The MVP should not add new runtime dependencies unless implementation hits a proven gap. The planned implementation uses:

- `fastmcp.FastMCP` for server construction
- `fastmcp.server.auth.TokenVerifier` and `fastmcp.server.auth.AccessToken` for bearer-token validation
- `fastmcp.resources.ResourceResult` and `fastmcp.resources.ResourceContent` for explicit Markdown resource responses
- Python stdlib for subprocess execution, JSON parsing, hashing, path handling, and constant-time token comparison

This does not override the project preference for libraries. The rule is:

- If the remaining work is straightforward glue around existing FastMCP and Obsidian CLI APIs, keep it in stdlib.
- If implementation would otherwise grow a real parser or state machine of its own, add a focused direct dependency with `uv add` rather than growing custom infrastructure.

For this MVP, the remaining custom logic is limited to task indexing, path mapping, cache bookkeeping, and light list-item normalization, so a new dependency is not yet justified.
For this MVP, the remaining custom logic is limited to task indexing, path mapping, cache bookkeeping, list-item normalization, and Markdown rendering, so a new dependency is not yet justified.

Alternatives considered:
- Add Starlette directly and build custom HTTP middleware: rejected as the default because FastMCP already exposes an auth-provider seam.
- Add a CLI wrapper library for Obsidian: rejected because the official CLI is already the source of truth and stdlib subprocess is sufficient.
- Add Pydantic models just for this MVP: rejected as a default because dict-based payload assembly is enough and avoids a new direct dependency.

### 2. Use FastMCP public APIs exactly as documented

The server should be built with the installed FastMCP public surface that was verified locally and against the official docs:

- `FastMCP(name, auth=...)` attaches an auth provider at the server level.
- `@mcp.resource(uri, mime_type=..., annotations=...)` registers the read surface.
- `@mcp.tool(name=..., annotations=...)` registers mutation tools.
- `mcp.run(transport="http", host=..., port=...)` remains the default bootstrap path.
- End-to-end verification should use `fastmcp.Client("http://127.0.0.1:8000/mcp", auth="<token>")`; FastMCP adds the `Bearer` prefix automatically when a raw token string is passed.

The concrete registration shape is:

```python
mcp = FastMCP("lmnop:handler", auth=ConfiguredTokenVerifier(...))

@mcp.resource(
    "obsidian://daily-standup",
    name="Daily Standup",
    description="The authoritative briefing for starting today's standup. Read this first when beginning the daily standup workflow. It contains the workflow guidance and the current vault data required to conduct the conversation: what matters now, what is coming soon, what still needs triage, what was recently resolved, and the recent note context needed to talk through it.",
    mime_type="text/markdown",
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
async def daily_standup_resource() -> ResourceResult: ...

@mcp.tool(
    name="append",
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def append_tool(target: str, content: str) -> dict: ...

@mcp.tool(
    name="resolve",
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def resolve_tool(id: str, resolution: str) -> dict: ...
```

`obsidian://daily-standup` should return `ResourceResult(contents=[ResourceContent(content=payload, mime_type="text/markdown")])` so the response is explicitly rendered as Markdown.

Alternatives considered:
- Return JSON or JSONC as the primary wire format: rejected because the only consumer is an agent reading the briefing, and Markdown keeps the workflow description plus the current data in one place with less punctuation noise.
- Use `http_app()` as the primary bootstrap path: rejected as the default because `run(..., transport="http")` is sufficient while the server stays standalone.

### 3. Implement bearer auth as a custom `TokenVerifier`

The authentication requirement is simple: one bearer token per client, revocable independently, with no external identity provider. The implementation should therefore create a small project-local verifier by subclassing `fastmcp.server.auth.TokenVerifier` and implementing `async def verify_token(self, token: str) -> AccessToken | None`.

Configuration contract:

- Store configured client tokens in an environment-backed mapping of `client_id -> token`
- Compare the presented token against configured values with `secrets.compare_digest`
- On match, return `AccessToken(token=token, client_id=client_id, scopes=[], claims={"client_id": client_id})`
- On miss, return `None`

This keeps auth boring and explicit while still using FastMCP's supported transport-level auth path.

Alternatives considered:
- `StaticTokenVerifier`: rejected because the FastMCP docs mark it as testing/development only.
- `DebugTokenVerifier`: rejected because the FastMCP docs position it for prototyping/testing rather than a public endpoint.
- `JWTVerifier`: rejected because this MVP does not have a token issuer, JWKS endpoint, or JWT issuance flow to integrate with.
- Shared single token: rejected because independent revocation per client is a stated requirement.

### 4. Execute Obsidian CLI commands through async subprocesses with explicit vault targeting and startup readiness

The implementation should call the official Obsidian CLI with `asyncio.create_subprocess_exec(...)`, not shell strings. Each command must be passed as discrete argv segments so content is not shell-escaped by hand.

Examples:

```python
await create_subprocess_exec("obsidian", f"vault={vault}", "daily:append", f"content={content}")
await create_subprocess_exec("obsidian", f"vault={vault}", "task", f"ref={ref}", "done")
await create_subprocess_exec("obsidian", f"vault={vault}", "tasks", "todo", "verbose", "format=json")
```

Command wrapper rules:

- All automated tests must target `tests/vault/handler-test-vault/` explicitly. The wrapper should therefore support a configured vault working directory and an optional `vault=<name-or-id>` selector prepended as the first argv parameter when available.
- Decode stdout/stderr as UTF-8 text.
- For JSON commands, parse stdout with `json.loads`.
- Treat any non-zero exit code as an error surfaced back through the MCP tool/resource.
- Preserve stderr text in the raised error so CLI failures remain debuggable.
- Do not use shell pipes, shell quoting, or shell interpolation.

The wrapper must hide the desktop-app startup quirk described in review: if Obsidian is not already running, the first CLI command may become the long-running app-launch process and not perform the requested action. The implementation contract is therefore:

1. Keep an optional owned Obsidian process handle in the adapter.
2. Before each intended CLI command, check whether the owned handle exists and is still alive. If it is alive, run the intended command normally.
3. If there is no live owned handle, start the intended command itself first.
4. If that command exits promptly, treat it as a normal command result and return it immediately. This is the path where another Obsidian instance was already running, so the handler does not own a process.
5. If that command does not exit within a short launch-detection window, treat it as the long-running Obsidian app process, retain the handle, and do not assume the requested action happened.
6. After adopting that handle, poll readiness by rerunning the same intended command as short-lived checks until one succeeds or a bounded startup timeout elapses.
7. If the owned handle later exits, clear it and repeat the same launch-detection flow on the next command.

`obsidian daily:path` remains the cheapest generic readiness check when the adapter needs one for diagnostics or warm-up, but the default startup path should use the intended command itself so successful commands are not executed twice.

Alternatives considered:
- `subprocess.run(..., shell=True)`: rejected for quoting and injection risk.
- Wrapping the CLI in a separate helper binary: rejected as unnecessary surface area.
- Requiring callers to start Obsidian manually before every request: rejected because the server should absorb that operational quirk itself.

### 5. `obsidian://daily-standup` is the single read model

The resource is the authoritative briefing for starting a daily standup. It must contain both:

1. the workflow description the agent is expected to follow
2. the current vault data required to carry that workflow out

The resource body is Markdown, not JSON. It should be self-describing so the consumer does not need a second resource to understand what each section means or why it matters.

The briefing is organized into five sections:

- `today_focus` — open tasks that matter now (overdue or scheduled today)
- `upcoming` — open tasks scheduled within a short planning window, controlled by `UPCOMING_DAYS = 7`
- `recent_unscheduled` — recently authored open tasks with no schedule yet; these require triage into either “pick a date” or “skip”
- `recent_resolutions` — recently completed or dropped tasks; carried tasks are not repeated here as normal actionable items because the carried copy belongs in `today_focus`
- `recent_notes` — recent non-task bullets that matter for continuity

The resource should render those sections with one sentence for what the section is and one sentence for why the user cares. A representative shape is:

```md
# Daily Standup

This is the authoritative briefing for today's standup. Use it to conduct the conversation.

## Today focus
What this is: Open tasks that matter now.
Why you care: This is today's working set.

3497: - [ ] Throw it on the NAS and kick the tires

## Upcoming
What this is: Open tasks scheduled soon.
Why you care: These may need prerequisites or advance attention.

ab38: - [/] Research MCP auth edge cases ⏳ 2026-05-19

## Recent unscheduled
What this is: Fresh open tasks with no schedule yet.
Why you care: Each one needs triage: pick a date or skip.

f911: - [-] Book dentist

## Recent resolutions
What this is: Recently completed or dropped tasks.
Why you care: This is the short accountability trail.

91aa: - [x] Verify line field shape

## Recent notes
What this is: Recent non-task bullets.
Why you care: They provide context that may matter to the conversation.

____: * Found this really great tool, Langfuse https://langfuse.ai
3497:   * [ ] Throw it on the NAS and kick the tires
```

Section contract:

- `today_focus` includes open tasks that are overdue or scheduled today.
- `upcoming` includes open tasks scheduled within `UPCOMING_DAYS`; tasks far in the future are intentionally omitted from the standup briefing.
- `recent_unscheduled` includes recently authored open tasks with no schedule; the expected workflow is to either assign a date or explicitly skip for now.
- `skip` is ephemeral for the MVP: it leaves the task unchanged in the vault and only means "do not schedule this right now."
- `recent_resolutions` includes only done and dropped items in the compact accountability view. Carried tasks are represented by their new actionable copy in `today_focus`.
- `recent_notes` includes non-task bullets from recent journal notes when they may matter to the conversation.

Formatting contract:

- Preserve the original Obsidian task line verbatim after the ID prefix, including status marker, indentation, and text.
- Do not collapse task statuses into a simplified vocabulary; show the source status marker exactly as written.
- Preserve indentation as note context only. Indentation does not imply dependency, parenthood, or association.
- When a task is nested under non-task bullets, render the minimal surrounding note tree once rather than repeating the ancestor chain for each task.
- Prefix actionable task lines with their MCP IDs in the form `<id>:`.
- Prefix contextual non-task lines with `____:` so human debugging can distinguish context lines from actionable lines.
- If a nested task appears under a non-task bullet, preserve that bullet in the rendered tree so the agent sees why the task is nested.

Exact command plan:

- `obsidian daily:path` → today's journal path, even if the file does not exist yet
- `obsidian daily:read` → today's journal contents
- Derive the daily-note folder from the parent directory of `daily:path`
- `obsidian files folder=<derived-daily-folder> ext=md` → enumerate prior journal-note candidates in that configured daily folder
- `obsidian read path=<recent-daily-path>` → read each recent journal note body
- `obsidian tasks path=<recent-daily-path> todo verbose format=json` → incomplete tasks authored in a recent journal note
- `obsidian tasks path=<recent-daily-path> done verbose format=json` → completed tasks authored in a recent journal note
- `obsidian tasks path=<recent-daily-path> status=- verbose format=json` → dropped tasks authored in a recent journal note
- `obsidian tasks path=<recent-daily-path> status=> verbose format=json` → carried tasks authored in a recent journal note
- `obsidian tasks todo verbose format=json` → incomplete tasks across the vault for standup assembly

Scheduled-today assembly contract:

- Start from `obsidian tasks todo verbose format=json`.
- The CLI output has stable `path` and `line` fields, and the returned task text is complete enough to inspect for scheduling markers directly.
- The `line` field is a string in the JSON output. The implementation must parse it to an integer before building `ref=<path:line>` or indexing source lines.
- Prefer an explicit machine-readable scheduled-date field if the CLI exposes one.
- Otherwise, inspect the returned task text for the standard scheduled-date marker and place the task into `today_focus`, `upcoming`, or neither based on its horizon relative to today.

Recent-note selection contract:

- Recent journal-note inspection replaces the earlier `yesterday` field entirely.
- Recent notes are selected by lexical path order within the derived daily-note folder, strictly before today's path.
- The count is bounded by a code constant named `RECENT_DAILY_NOTE_COUNT`, fixed at `2` for the MVP.
- If there are no prior journal notes, sections that depend on recent journal history simply render with no items.

Planning-window contract:

- `UPCOMING_DAYS` defines the near-future horizon for `upcoming` and is fixed at `7` for the MVP.
- Tasks scheduled beyond `UPCOMING_DAYS` are omitted from the standup briefing.
- A task authored recently but scheduled far in the future is omitted from the standup briefing, because it is neither actionable now nor near enough to plan against.

Project grouping contract:

- Project grouping is derived only from paths matching `notes/projects/{project-directory}/.minutes.md`.
- The project key is the directory name immediately below `notes/projects/`.
- No slugging, title normalization, alias resolution, or file-stem extraction happens in the server.

Alternatives considered:
- Separate resources for workflow description and current data: rejected because the standup consumer needs both, and splitting them creates a missable dependency.
- Separate resources for recent notes, scheduled tasks, and current note state: rejected because clients would need multiple round-trips before they can talk.
- `tasks daily ...` for prior-note state: rejected because the official CLI documents `tasks daily` as today's daily note, not arbitrary previous journal notes.
- Calendar-yesterday only: rejected because skipped days would hide the real previous context.

### 6. `append` is the only content mutation tool

`append` accepts:

```json
{
  "target": "daily | <project-directory>",
  "content": "one or more markdown list items"
}
```

Target mapping contract:

- `target="daily"` means today's journal note
- Any other target is treated as the exact project directory name under `notes/projects/`; for example `eavesdrop` maps to `notes/projects/eavesdrop/.minutes.md`

List-item contract:

- The tool appends one or more markdown list items, not arbitrary free-form paragraphs.
- Nested list indentation is preserved exactly as provided.
- If the first non-whitespace character of an appended top-level item is not already a markdown list marker (`-`, `*`, or `+`), the server prefixes `- ` before writing.
- The server does not otherwise rewrite the markdown body.

Exact command plan:

- Daily append: `obsidian daily:append content=<text>`
- Project append: `obsidian append path=notes/projects/<target>/.minutes.md content=<text>`
- Missing project note creation: `obsidian create path=notes/projects/<target>/.minutes.md content=<text>` then append subsequent writes with `obsidian append ...`

Daily-note creation contract:

- If today's journal note does not exist yet, `obsidian daily:append` is responsible for creating it.
- The MVP should therefore not issue a separate `daily` or `create` command before a normal daily append.

Behavior contract:

- Content is appended with the CLI's normal append semantics.
- The server scans appended markdown for task lines.
- Returned `new_tasks` IDs must be computed from the post-write task index, not from the appended snippet in isolation, so collision numbering matches the current vault state.

Response shape:

```json
{
  "success": true,
  "target_path": "journal/2026-05-17.md",
  "new_tasks": {
    "h8e1": "Build MCP auth endpoint"
  }
}
```

Field justification:

- `success` keeps mutation responses uniform with `resolve`.
- `target_path` confirms where the content actually landed after target mapping and possible note creation.
- `new_tasks` returns only the new handles created by this append, in the smallest useful shape: `id -> task text`.

Alternatives considered:
- Distinct write tools for notes, brainstorms, and tasks: rejected because the markdown append model already covers all three without adding API surface.
- Accepting arbitrary prose blocks with no list normalization: rejected because the target notes are specifically maintained as unordered lists.
- Automatic slugification of project names: rejected because it creates hidden filename rules and makes round-tripping less predictable.

### 7. `resolve` is the only task status mutation tool

`resolve` accepts:

```json
{
  "id": "a3f1",
  "resolution": "done | dropped | carried"
}
```

Resolution contract:

- `done` marks the current task complete in place.
- `dropped` marks the current task abandoned in place with status `-`.
- `carried` means "this task was not completed here; move it forward into today's journal note while preserving the historical record where it came from."

`carried` has a two-part effect:

1. Change the original task in its source note to status `>`.
2. Append a fresh `- [ ] ...` copy of the same task body to today's journal note.

Query consequences of `carried`:

- The original task is no longer treated as an open task.
- The original task remains marked as carried in its source note for human history, but it is not surfaced as a normal actionable item in the standup briefing.
- The newly appended copy is a new open task with a new derived ID.
- If the copied task body still carries a scheduled marker, it may appear in `today_focus` or `upcoming` after the next re-read, depending on its horizon. That is expected.

Exact command plan:

- `done` → `obsidian task ref=<path:line> done`
- `dropped` → `obsidian task ref=<path:line> status=-`
- `carried` → `obsidian task ref=<path:line> status=>`, then `obsidian daily:append content="- [ ] ..."`

Response shape:

```json
{
  "success": true,
  "id": "a3f1",
  "text": "Build auth endpoint",
  "resolution": "done",
  "new_id": null
}
```

Field justification:

- `success` confirms the mutation completed.
- `id` echoes the resolved handle the caller asked to mutate.
- `text` confirms the human task text that was actually matched before mutation.
- `resolution` confirms which resolution path was applied.
- `new_id` is `null` for in-place resolutions and populated only for `carried`, because carrying creates a new task instance in today's journal note.

The tool resolves the ID against the current vault state first, then uses the matched task's current CLI ref internally for mutation.

Alternatives considered:
- Let clients update checkbox syntax directly: rejected because it exposes line-level vault mechanics and breaks the clean task-oriented API.
- Keep carried tasks incomplete in place: rejected because `- [>]` communicates explicit migration history in the source note.

### 8. Task IDs use SHA-256 over `file_path + task_text`, with per-client caching

The implementation contract is explicit:

```text
base = sha256(f"{file_path}: {task_text}".encode("utf-8")).hexdigest()[:4]
```

If multiple current tasks share the same base hash, IDs are assigned in source order:

- first: `{base}`
- second: `{base}-1`
- third: `{base}-2`

Properties:

- No persistent state is needed.
- No task metadata is written into the vault.
- IDs are recomputable from current CLI-visible data.
- IDs intentionally change if the task text changes or the file moves.

Canonical indexing fields are:

- `path` — vault-relative file path
- `line` — current line number used to build `ref=<path:line>`, sourced from the CLI JSON as a string and normalized to an integer in memory
- `text` — current task text without the checkbox marker
- `status` — current status character / logical status

To avoid rescanning the full task set on every single resolve, the server should keep a small in-memory cache per authenticated client:

- Cache key: `client_id`
- Cached value: assembled task index plus the file metadata needed to validate it (`path -> (size, mtime_ns)` is sufficient)
- `obsidian://daily-standup` may populate or refresh that cache
- `resolve` may reuse the cache only if the watched file metadata still matches; otherwise it must rebuild before matching the ID
- After `done` or `dropped`, update or invalidate only the affected cached entries rather than forcing a full-vault rescan
- After `carried`, refresh only the source note and today's journal note in cache rather than the entire vault when possible

Correctness rule: cache reuse is an optimization only. If cached state cannot be proven current, the implementation must rebuild from live CLI-visible state before mutating.

Alternatives considered:
- Persistent UUIDs written into task lines: rejected because they pollute the vault.
- Line-number-based IDs: rejected because line movement is incidental and not the contract.
- Unspecified hash function: rejected because visible IDs would become implementation-defined.
- Full-vault rescan on every single resolve even when nothing changed: rejected because the server already has a per-client auth boundary and can safely keep a small validated cache.

### 9. Sync remains out of band

`append` and `resolve` return when the local vault mutation succeeds. Any downstream syncing mechanism runs separately and is not part of request success.

Alternatives considered:
- Block writes on sync completion: rejected because it couples local note mutation latency and reliability to downstream sync behavior.

## Risks / Trade-offs

- [Task ID instability after edits or moves] → Accept this as part of the contract and force clients to refresh context when an ID no longer resolves.
- [Hash collisions within the current task set] → Number colliding IDs in source order so every current task still has a unique short handle.
- [Static bearer tokens are secret material] → Keep tokens in environment-backed config, compare with `secrets.compare_digest`, and never log token values.
- [Obsidian startup readiness is not the same as process launch] → Treat the intended command as the initial launch probe, retain the process only when that invocation becomes the long-running app launcher, and retry only after readiness is established.
- [Path-based project grouping depends on vault conventions] → Scope the MVP to `notes/projects/{project}/.minutes.md` and treat other layouts as out of scope.
- [Concurrent mutations can race] → Keep last-write-wins semantics for MVP and re-read or revalidate current state before every resolve.
- [Some Obsidian CLI machine-readable shapes are not fully documented] → Capture real command output during implementation and keep parsing logic narrow to the observed shape.

## Migration Plan

1. Replace the demo hello-world MCP surface with the authenticated Obsidian-backed surface.
2. Add the project-local `TokenVerifier` implementation and wire it into `FastMCP(..., auth=...)`.
3. Implement the Obsidian CLI adapter layer around `asyncio.create_subprocess_exec(...)`, including owned-process launch detection, readiness retries, and explicit test-vault targeting.
4. Implement daily-standup briefing assembly, append, and resolve on top of the verified CLI command set documented above.
5. If implementation proves a direct import dependency is necessary, add it with `uv add` rather than editing dependency files by hand.
6. Verify the server against `tests/vault/handler-test-vault/` and a real vault using journal notes plus project minutes notes under `notes/projects/`, with `obsidian://daily-standup` rendering the full Markdown briefing described above.
7. Roll back by restoring the previous demo server entrypoint if the Obsidian integration is not yet usable.

## Open Questions

- None.
