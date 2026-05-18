## Why

The current server is only a hello-world FastMCP endpoint and does not expose any useful workflow to Claude or ChatGPT. The MVP is to turn it into a real Obsidian-backed MCP server that supports the user's daily planning loop: reading recent journal context, seeing what is scheduled for today, capturing new list items, and resolving existing tasks without touching raw vault files directly. This needs to stay voice-friendly, so workflow shaping belongs in the client while the server exposes only the smallest useful MCP surface. The change is needed now to replace the placeholder server with an end-to-end integration that can be used from hosted assistants against a live Obsidian vault.

## What Changes

- Replace the demo surface with one MCP resource, `obsidian://daily-standup`, that returns the full Markdown briefing required to conduct the daily standup: workflow guidance plus the current standup data.
- Add an `append` tool that writes one or more markdown list items to today's journal note or a project minutes note under `notes/projects/{project}/.minutes.md` and returns short IDs for any newly created tasks.
- Add a `resolve` tool that updates task status by short ID using the current vault state, supporting `done`, `dropped`, and `carried` resolutions.
- Introduce deterministic short task IDs derived from `file_path + task_text`, with collision numbering in source order.
- Remove the hello-world behavior from the MVP surface.

## Impact

Affected code includes the FastMCP server entrypoint, request authentication, Obsidian CLI integration, vault/task parsing, Markdown briefing rendering, and tool/resource definitions. The public MCP contract changes from a demo tool to a production MVP contract centered on `obsidian://daily-standup`, `append`, and `resolve`. The server depends on a locally running Obsidian app with CLI/IPC access, reuses an already running instance when present, adopts a long-running process handle only when it becomes the launcher itself, and assumes daily notes plus project minutes notes under `notes/projects/{project}/.minutes.md`.
