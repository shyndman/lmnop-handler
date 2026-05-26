from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Protocol

from .config import (
    LoadedSettings,
    Settings,
    format_settings_report,
    load_loaded_settings,
)
from .models import (
    AppendResult,
    FileSnapshot,
    StandupSection,
    TaskIndex,
    TaskRecord,
    TaskStatusResult,
)
from .obsidian_cli import ObsidianCli
from .standup import render_standup_markdown
from .task_domain import (
    TASK_QUERY_SELECTORS,
    TOOL_TASK_STATUSES,
    classify_schedule,
    is_done_task_status,
    normalize_list_content,
    render_note_block,
    render_recent_notes,
    task_status_mutation,
)


class ObsidianCliLike(Protocol):
    async def daily_path(self) -> str: ...
    async def read_note(self, path: str) -> str: ...
    async def list_markdown_files(self, folder: str) -> list[str]: ...
    async def list_tags(self) -> list[str]: ...
    async def query_tasks(
        self, selector: str, *, path: str | None = None
    ) -> list[TaskRecord]: ...
    async def append_daily(self, content: str) -> None: ...
    async def mutate_task(self, ref: str, status: str) -> None: ...
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
                if is_done_task_status(task.status):
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
            StandupSection(
                title="Today focus",
                what="Open tasks that matter now.",
                why="This is today's working set.",
                groups=await self._render_task_groups(today_focus, full_id_map),
            ),
            StandupSection(
                title="Upcoming",
                what="Open tasks scheduled soon.",
                why="These may need prerequisites or advance attention.",
                groups=await self._render_task_groups(upcoming, full_id_map),
            ),
            StandupSection(
                title="Recent unscheduled",
                what="Fresh open tasks with no schedule yet.",
                why="Each one needs triage: pick a date or skip.",
                groups=await self._render_task_groups(recent_unscheduled, full_id_map),
            ),
            StandupSection(
                title="Recent resolutions",
                what="Recently completed or dropped tasks.",
                why="This is the short accountability trail.",
                groups=await self._render_task_groups(
                    recent_done + recent_dropped, full_id_map
                ),
            ),
            StandupSection(
                title="Recent notes",
                what="Recent non-task bullets.",
                why="They provide context that may matter to the conversation.",
                groups=recent_notes,
            ),
        ]

        return render_standup_markdown(today, sections, await self._project_tags())

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

    async def set_task_status(
        self, client_id: str, task_id: str, status: str
    ) -> TaskStatusResult:
        if status not in TOOL_TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")

        index = await self._get_open_index(client_id)
        task = index.by_id.get(task_id)
        if task is None:
            _ = self._open_task_cache.pop(client_id, None)
            index = await self._get_open_index(client_id)
            task = index.by_id.get(task_id)
        if task is None:
            raise ValueError(f"Unknown open task id: {task_id}")

        await self._cli.mutate_task(task.ref, task_status_mutation(status))

        await self._refresh_open_index(client_id, {task.path})
        return TaskStatusResult(id=task_id, text=task.text, status=status)

    async def _recent_daily_paths(self, today_path: str) -> list[str]:
        folder = PurePosixPath(today_path).parent.as_posix()
        all_paths = await self._cli.list_markdown_files(folder)
        prior = [path for path in sorted(all_paths) if path < today_path]
        return prior[-self._settings.recent_daily_note_count :]

    async def _project_tags(self) -> list[str]:
        tags = await self._cli.list_tags()
        return sorted(tag for tag in tags if tag.startswith("#project/"))

    async def _load_tasks_for_path(self, path: str) -> list[TaskRecord]:
        return await self._query_tasks(path=path)

    async def _build_full_task_id_map(self) -> dict[str, TaskRecord]:
        return TaskIndex(tasks=tuple(await self._query_tasks()), watched_files={}).by_id

    async def _query_tasks(self, *, path: str | None = None) -> list[TaskRecord]:
        seen: set[tuple[str, int, str, str]] = set()
        tasks: list[TaskRecord] = []
        for selector in TASK_QUERY_SELECTORS:
            for task in await self._cli.query_tasks(selector, path=path):
                key = (task.path, task.line, task.status, task.text)
                if key not in seen:
                    seen.add(key)
                    tasks.append(task)
        tasks.sort(key=lambda task: (task.path, task.line, task.text, task.status))
        return tasks

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

    async def set_task_status(
        self, client_id: str, task_id: str, status: str
    ) -> TaskStatusResult:
        return await self.application().set_task_status(client_id, task_id, status)
