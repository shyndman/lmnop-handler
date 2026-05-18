# Obsidian Voice Assistant — MCP Design

## Overview

A publicly accessible MCP server with Bearer token authentication that gives Claude and ChatGPT read/write access to an Obsidian vault. The server runs on a machine where Obsidian is running (the CLI communicates with the live app via IPC). Conversation flow and behaviour are handled client-side; the MCP surface stays minimal and workflow-oriented.

The MCP surface is intentionally small:
- one resource: `obsidian://daily-standup`
- two tools: `append`, `resolve`

CLI reference: https://retypeapp.github.io/obsidian/cli/

---

## Task Short IDs

Every task is identified by a short ID derived deterministically from its location and content:

```text
base = sha256(f"{file_path}: {task_text}".encode("utf-8")).hexdigest()[:4]
```

If multiple current tasks share the same base hash, IDs are assigned in source order:
- first: `{base}`
- second: `{base}-1`
- third: `{base}-2`

The server resolves IDs from current vault state on every `resolve` call, then mutates the matched task by current `ref=<path:line>`.

---

## Resource

### `obsidian://daily-standup`

This is the authoritative briefing for starting the daily standup. It is a one-stop shop containing:
1. the workflow description
2. the current data required to carry it out

The resource is returned as Markdown, not JSON. The body is self-describing so the consumer does not need a second resource to understand the workflow.

**Discovery metadata:**
- name/title: `Daily Standup`
- description: `The authoritative briefing for starting today's standup. Read this first when beginning the daily standup workflow. It contains the workflow guidance and the current vault data required to conduct the conversation: what matters now, what is coming soon, what still needs triage, what was recently resolved, and the recent note context needed to talk through it.`
- mime type: `text/markdown`

**Sections:**
- `today_focus` — open tasks that matter now
- `upcoming` — open tasks scheduled within `UPCOMING_DAYS = 7`
- `recent_unscheduled` — recently authored open tasks with no schedule; these need `date` or ephemeral `skip`
- `recent_resolutions` — recently done or dropped tasks
- `recent_notes` — recent non-task bullets for continuity

Carried tasks are not repeated here as normal resolution items; the carried copy belongs in `today_focus`.

**Rendering rules:**
- preserve the original Obsidian task line verbatim after the MCP prefix
- preserve status marker, indentation, and text exactly
- do not reduce statuses to a simplified vocabulary
- indentation is note context, not dependency or task parentage
- render nested tasks as a single note tree, not one ancestor chain per task
- prefix actionable task lines with `<id>:`
- prefix contextual non-task lines with `____:`

**Representative shape:**

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

____: * Found this really great tool, Langfuse https://langfuse.ai
3497:   * [ ] Throw it on the NAS and kick the tires

## Recent resolutions
What this is: Recently completed or dropped tasks.
Why you care: This is the short accountability trail.

91aa: - [x] Verify line field shape

## Recent notes
What this is: Recent non-task bullets.
Why you care: They provide context that may matter to the conversation.

____: * Need to be careful about line numbers being strings
```

**CLI commands used internally by the server:**
- `obsidian daily:path`
- `obsidian daily:read`
- `obsidian files folder=<derived-daily-folder> ext=md`
- `obsidian read path=<recent-daily-path>`
- `obsidian tasks path=<recent-daily-path> todo verbose format=json`
- `obsidian tasks path=<recent-daily-path> done verbose format=json`
- `obsidian tasks path=<recent-daily-path> status=- verbose format=json`
- `obsidian tasks path=<recent-daily-path> status=> verbose format=json`
- `obsidian tasks todo verbose format=json`

Notes:
- `RECENT_DAILY_NOTE_COUNT = 2`
- `UPCOMING_DAYS = 7` defines the near-future planning horizon
- far-future tasks are intentionally omitted from the standup briefing
- `line` values from `tasks ... verbose format=json` are strings and must be parsed to integers before building `ref=<path:line>`
- `skip` leaves an unscheduled task unchanged in the vault; it only means "do not schedule this right now"

---

## Tools

### `append`

Appends one or more markdown list items to today's journal note or a project's `notes/projects/{project}/.minutes.md` note.

**Parameters:**
- `target`: `daily | <project-directory>`
- `content`: one or more markdown list items

**Behaviour:**
- preserve nested list indentation exactly as provided
- if the first non-whitespace character of a top-level item is not already a list marker, prefix `- `
- for `daily`, rely on `obsidian daily:append` to create today's note if missing
- for project targets, create `notes/projects/<target>/.minutes.md` if missing
- compute `new_tasks` from the post-write task index, not the appended snippet in isolation

**Returns:**

```json
{
  "success": true,
  "target_path": "journal/2026-05-17.md",
  "new_tasks": {
    "h8e1": "Build MCP auth endpoint"
  }
}
```

### `resolve`

Resolves a task by short ID.

**Parameters:**
- `id`
- `resolution`: `done | dropped | carried`

**Semantics:**
- `done` → mark complete in place
- `dropped` → mark abandoned in place with status `-`
- `carried` → mark original task as `>` and append a new `- [ ]` copy to today's journal note

Carried tasks become part of today's actionable set through the newly appended copy.

**Returns:**

```json
{
  "success": true,
  "id": "a3f1",
  "text": "Build auth endpoint",
  "resolution": "done",
  "new_id": null
}
```

---

## Architecture Notes

**Server location:** The Obsidian CLI requires the desktop app to be running via IPC. The server must run on the same machine.

**Authentication:** Bearer tokens — one per client, revocable independently.

**Sync:** Vault sync is out of band.

**Vault structure assumed:**

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

The daily-note folder must be derived from `daily:path`, not hardcoded, because the test fixture currently uses `journals/`.
