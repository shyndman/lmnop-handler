from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from typing import ClassVar, Protocol

from fastmcp import Context, FastMCP
from fastmcp.resources import ResourceContent, ResourceResult
from pydantic import BaseModel, ConfigDict, Field

from .config import (
    LoadedSettings,
    Settings,
    format_settings_report,
    load_loaded_settings,
)
from .models import AppendResult, FileSnapshot, ResolveResult, TaskIndex, TaskRecord
from .obsidian import (
    ObsidianCli,
    classify_schedule,
    normalize_list_content,
    render_note_block,
    render_recent_notes,
    stripped_task_body,
)

RESOURCE_URI = "obsidian://daily-standup"
RESOURCE_NAME = "Daily Standup"
RESOURCE_DESCRIPTION = (
    "The authoritative briefing for starting today's standup. Read this first when "
    "beginning the daily standup workflow. It contains the workflow guidance and the "
    "current vault data required to conduct the conversation: what matters now, what "
    "is coming soon, what still needs triage, what was recently resolved, and the "
    "recent note context needed to talk through it."
)
TOOL_RESOLUTIONS = {"done", "dropped", "carried"}


class Section(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    title: str
    what: str
    why: str
    groups: list[tuple[str, str]] = Field(default_factory=list)


class ObsidianCliLike(Protocol):
    async def daily_path(self) -> str: ...
    async def read_note(self, path: str) -> str: ...
    async def list_markdown_files(self, folder: str) -> list[str]: ...
    async def list_tags(self) -> list[str]: ...
    async def query_tasks(
        self, selector: str, *, path: str | None = None
    ) -> list[TaskRecord]: ...
    async def append_daily(self, content: str) -> None: ...
    async def mutate_task(self, ref: str, resolution: str) -> None: ...
    def resolve_vault_path(self, path: str) -> Path: ...
    def snapshot_vault(self) -> Mapping[str, FileSnapshot]: ...
    def build_open_task_index(self, tasks: list[TaskRecord]) -> TaskIndex: ...
    def is_index_current(self, index: TaskIndex) -> bool: ...


class HandlerApplication:
    _settings: Settings
    _cli: ObsidianCliLike
    _open_task_cache: dict[str, TaskIndex]

    def __init__(self, settings: Settings, cli: ObsidianCliLike | None = None):
        self._settings = settings
        self._cli = cli or ObsidianCli(settings)
        self._open_task_cache = {}

    @property
    def settings(self) -> Settings:
        return self._settings

    async def daily_standup(self, client_id: str) -> str:
        today_path = await self._cli.daily_path()
        today = date.today()
        recent_paths = await self._recent_daily_paths(today_path)
        full_id_map = await self._build_full_task_id_map()
        all_open = await self._get_open_index(client_id)

        today_focus: list[TaskRecord] = []
        upcoming: list[TaskRecord] = []
        for task in all_open.tasks:
            bucket = classify_schedule(task, today, self._settings.upcoming_days)
            if bucket == "today_focus":
                today_focus.append(task)
            elif bucket == "upcoming":
                upcoming.append(task)

        recent_open: list[TaskRecord] = []
        recent_done: list[TaskRecord] = []
        recent_dropped: list[TaskRecord] = []
        recent_notes: list[tuple[str, str]] = []
        for path in recent_paths:
            tasks = await self._load_tasks_for_path(path)
            for task in tasks:
                if task.status in {"x", "X"}:
                    recent_done.append(task)
                elif task.status == "-":
                    recent_dropped.append(task)
                elif task.is_open:
                    recent_open.append(task)
            note_block = render_recent_notes(await self._cli.read_note(path))
            if note_block:
                recent_notes.append((f"Note: {path}", note_block))

        recent_unscheduled = [
            task
            for task in recent_open
            if classify_schedule(task, today, self._settings.upcoming_days) is None
        ]

        sections = [
            Section(
                title="Today focus",
                what="Open tasks that matter now.",
                why="This is today's working set.",
                groups=await self._render_task_groups(today_focus, full_id_map),
            ),
            Section(
                title="Upcoming",
                what="Open tasks scheduled soon.",
                why="These may need prerequisites or advance attention.",
                groups=await self._render_task_groups(upcoming, full_id_map),
            ),
            Section(
                title="Recent unscheduled",
                what="Fresh open tasks with no schedule yet.",
                why="Each one needs triage: pick a date or skip.",
                groups=await self._render_task_groups(recent_unscheduled, full_id_map),
            ),
            Section(
                title="Recent resolutions",
                what="Recently completed or dropped tasks.",
                why="This is the short accountability trail.",
                groups=await self._render_task_groups(
                    recent_done + recent_dropped, full_id_map
                ),
            ),
            Section(
                title="Recent notes",
                what="Recent non-task bullets.",
                why="They provide context that may matter to the conversation.",
                groups=recent_notes,
            ),
        ]

        return self._render_standup_markdown(sections, await self._project_tags())

    async def append(self, client_id: str, content: str) -> AppendResult:
        normalized = normalize_list_content(content)
        if not normalized.strip():
            raise ValueError("append content must contain at least one list item")

        target_path = await self._cli.daily_path()
        target_file = self._cli.resolve_vault_path(target_path)
        before_line_count = (
            len(target_file.read_text(encoding="utf-8").splitlines())
            if target_file.exists()
            else 0
        )

        await self._cli.append_daily(normalized)

        full_id_map = await self._build_full_task_id_map()
        new_tasks = self._extract_new_tasks(target_path, before_line_count, full_id_map)
        await self._refresh_open_index(client_id, {target_path})
        return AppendResult(target_path=target_path, new_tasks=new_tasks)

    async def resolve(
        self, client_id: str, task_id: str, resolution: str
    ) -> ResolveResult:
        if resolution not in TOOL_RESOLUTIONS:
            raise ValueError(f"Unsupported resolution: {resolution}")

        index = await self._get_open_index(client_id)
        task = index.by_id.get(task_id)
        if task is None:
            _ = self._open_task_cache.pop(client_id, None)
            index = await self._get_open_index(client_id)
            task = index.by_id.get(task_id)
        if task is None:
            raise ValueError(f"Unknown open task id: {task_id}")

        affected_paths = {task.path}
        new_id: str | None = None
        if resolution == "done":
            await self._cli.mutate_task(task.ref, "done")
        elif resolution == "dropped":
            await self._cli.mutate_task(task.ref, "status=-")
        else:
            await self._cli.mutate_task(task.ref, "status=>")
            today_path = await self._cli.daily_path()
            today_file = self._cli.resolve_vault_path(today_path)
            before_line_count = (
                len(today_file.read_text(encoding="utf-8").splitlines())
                if today_file.exists()
                else 0
            )
            await self._cli.append_daily(f"- [ ] {stripped_task_body(task.raw_line)}")
            full_id_map = await self._build_full_task_id_map()
            new_tasks = self._extract_new_tasks(
                today_path, before_line_count, full_id_map
            )
            new_id = next(iter(new_tasks), None)
            affected_paths.add(today_path)

        await self._refresh_open_index(client_id, affected_paths)
        return ResolveResult(
            id=task_id, text=task.text, resolution=resolution, new_id=new_id
        )

    async def _recent_daily_paths(self, today_path: str) -> list[str]:
        folder = PurePosixPath(today_path).parent.as_posix()
        all_paths = await self._cli.list_markdown_files(folder)
        prior = [path for path in sorted(all_paths) if path < today_path]
        return prior[-self._settings.recent_daily_note_count :]

    async def _project_tags(self) -> list[str]:
        tags = await self._cli.list_tags()
        return sorted(tag for tag in tags if tag.startswith("#project/"))

    async def _load_tasks_for_path(self, path: str) -> list[TaskRecord]:
        seen: set[tuple[str, int, str, str]] = set()
        tasks: list[TaskRecord] = []
        for selector in ("todo", "done", "status=-", "status=>"):
            for task in await self._cli.query_tasks(selector, path=path):
                key = (task.path, task.line, task.status, task.text)
                if key not in seen:
                    seen.add(key)
                    tasks.append(task)
        tasks.sort(key=lambda task: (task.path, task.line, task.text, task.status))
        return tasks

    async def _build_full_task_id_map(self) -> dict[str, TaskRecord]:
        seen: set[tuple[str, int, str, str]] = set()
        tasks: list[TaskRecord] = []
        for selector in ("todo", "done", "status=-", "status=>"):
            for task in await self._cli.query_tasks(selector):
                key = (task.path, task.line, task.status, task.text)
                if key not in seen:
                    seen.add(key)
                    tasks.append(task)
        tasks.sort(key=lambda task: (task.path, task.line, task.text, task.status))
        return TaskIndex(tasks=tuple(tasks), watched_files={}).by_id

    async def _get_open_index(self, client_id: str) -> TaskIndex:
        cached = self._open_task_cache.get(client_id)
        if cached is not None and self._cli.is_index_current(cached):
            return cached
        tasks = await self._cli.query_tasks("todo")
        index = self._cli.build_open_task_index(tasks)
        self._open_task_cache[client_id] = index
        return index

    async def _refresh_open_index(self, client_id: str, paths: set[str]) -> None:
        cached = self._open_task_cache.get(client_id)
        if cached is None or not self._cli.is_index_current(cached):
            tasks = await self._cli.query_tasks("todo")
            self._open_task_cache[client_id] = self._cli.build_open_task_index(tasks)
            return

        replacements: list[TaskRecord] = []
        for path in paths:
            replacements.extend(await self._cli.query_tasks("todo", path=path))
        self._open_task_cache[client_id] = cached.replace_paths(
            paths, replacements, self._cli.snapshot_vault()
        )

    async def _render_task_groups(
        self,
        tasks: Iterable[TaskRecord],
        full_id_map: dict[str, TaskRecord],
    ) -> list[tuple[str, str]]:
        rendered: list[tuple[str, str]] = []
        tasks_by_path: dict[str, list[TaskRecord]] = defaultdict(list)
        id_by_ref = {task.ref: task_id for task_id, task in full_id_map.items()}
        for task in tasks:
            tasks_by_path[task.path].append(task)

        for path in sorted(tasks_by_path):
            note_text = await self._cli.read_note(path)
            path_tasks = sorted(tasks_by_path[path], key=lambda task: task.line)
            target_lines = {
                task.line: id_by_ref[task.ref]
                for task in path_tasks
                if task.ref in id_by_ref
            }
            if not target_lines:
                continue
            rendered.append(
                (path_tasks[0].source_label, render_note_block(note_text, target_lines))
            )
        return rendered

    def _extract_new_tasks(
        self,
        path: str,
        before_line_count: int,
        full_id_map: dict[str, TaskRecord],
    ) -> dict[str, str]:
        ids_by_ref = {task.ref: task_id for task_id, task in full_id_map.items()}
        tasks_for_file = [
            task
            for task in full_id_map.values()
            if task.path == path and task.line > before_line_count
        ]
        tasks_for_file.sort(key=lambda task: task.line)
        return {
            ids_by_ref[task.ref]: task.text
            for task in tasks_for_file
            if task.ref in ids_by_ref
        }

    def _render_standup_markdown(
        self, sections: list[Section], project_tags: list[str]
    ) -> str:
        lines = [
            "# Daily Standup",
            "",
            "This is the authoritative briefing for today's standup. Use it to conduct the conversation.",
            "",
            "Workflow:",
            "1. Work through Today focus first.",
            "2. Review Upcoming for near-term preparation.",
            "3. For each Recent unscheduled item, pick a date or say skip.",
            "4. Review Recent resolutions and Recent notes for continuity.",
            "5. Capture notes with append_note as bullets or nested bullets.",
            (
                "6. When a note has to do with a project, it MUST be marked "
                "with the matching #project/ tag."
            ),
            "7. Available project tags:",
            *(f"   - {tag}" for tag in project_tags),
            (
                "8. Preserve task status markers: [ ] unchecked, [x] checked, "
                "[>] rescheduled, [<] scheduled, [!] important, [-] cancelled, "
                "[/] in progress, [?] question, [*] star, [n] note, [l] location, "
                "[i] information, [I] idea, [S] amount, [p] pro, [c] con, "
                '[b] bookmark, ["] quote.'
            ),
            "",
            "Task emoji syntax (from docs/emoji_task_format.md):",
            (
                "- Dates: ➕ created, ⏳ scheduled, 🛫 start, 📅 due, "
                "✅ done, ❌ cancelled; all dates use YYYY-MM-DD."
            ),
            "- Priorities: ⏬ lowest, 🔽 low, no marker normal, 🔼 medium, ⏫ high, 🔺 highest.",
            "- Recurrence: 🔁 followed by the rule, e.g. 🔁 every day when done.",
            "- On completion: 🏁 keep or 🏁 delete.",
            "- Dependencies: 🆔 task-id defines an id; ⛔ id1,id2 blocks on ids.",
            (
                "- Daily-note placement alone does not make a task due today or active "
                "today; use an explicit 📅, ⏳, or 🛫 date marker."
            ),
        ]
        for section in sections:
            lines.extend(
                [
                    "",
                    f"## {section.title}",
                    f"What this is: {section.what}",
                    f"Why you care: {section.why}",
                ]
            )
            for label, block in section.groups:
                lines.extend(["", f"### {label}", block])
        return "\n".join(lines) + "\n"


class EnvironmentApplication:
    _env: Mapping[str, str]
    _application: HandlerApplication | None
    _loaded_settings: LoadedSettings | None

    def __init__(self, env: Mapping[str, str] | None = None):
        self._env = env or os.environ
        self._application = None
        self._loaded_settings = None

    def loaded_settings(self) -> LoadedSettings:
        if self._loaded_settings is None:
            self._loaded_settings = load_loaded_settings(self._env)
        return self._loaded_settings

    def settings(self) -> Settings:
        return self.loaded_settings().settings

    def startup_report(self) -> str:
        return format_settings_report(self.loaded_settings())

    def application(self) -> HandlerApplication:
        if self._application is None:
            self._application = HandlerApplication(self.settings())
        return self._application

    async def daily_standup(self, client_id: str) -> str:
        return await self.application().daily_standup(client_id)

    async def append(self, client_id: str, content: str) -> AppendResult:
        return await self.application().append(client_id, content)

    async def resolve(
        self, client_id: str, task_id: str, resolution: str
    ) -> ResolveResult:
        return await self.application().resolve(client_id, task_id, resolution)


def create_mcp(runtime: HandlerApplication | EnvironmentApplication) -> FastMCP:
    mcp = FastMCP("lmnop:handler")

    @mcp.resource(
        RESOURCE_URI,
        name=RESOURCE_NAME,
        description=RESOURCE_DESCRIPTION,
        mime_type="text/markdown",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def daily_standup_resource(ctx: Context) -> ResourceResult:
        payload = await runtime.daily_standup(ctx.client_id or "")
        return ResourceResult(
            contents=[ResourceContent(content=payload, mime_type="text/markdown")]
        )

    @mcp.tool(
        name="append_note",
        description=(
            "Append content to today's daily note. During standup, use this proactively "
            "to capture decisions, context, and new tasks as they arise; do not ask "
            "for confirmation first unless the content is ambiguous. Notes are stored "
            "as outliner bullets; plain lines are converted to bullets."
        ),
        annotations={
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def append_note_tool(content: str, ctx: Context) -> dict[str, object]:
        return (await runtime.append(ctx.client_id or "", content)).model_dump(
            mode="python"
        )

    @mcp.tool(
        name="resolve_task",
        annotations={
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def resolve_task_tool(
        id: str, resolution: str, ctx: Context
    ) -> dict[str, object]:
        return (await runtime.resolve(ctx.client_id or "", id, resolution)).model_dump(
            mode="python"
        )

    from .transforms import StandupTool

    _ = (daily_standup_resource, append_note_tool, resolve_task_tool)

    mcp.add_transform(
        StandupTool(
            resource_uri=RESOURCE_URI,
            resource_description=RESOURCE_DESCRIPTION,
        )
    )
    return mcp
