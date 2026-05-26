from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import ClassVar, Protocol, cast, final

from pydantic import BaseModel, ConfigDict

from .config import Settings
from .models import FileSnapshot, TaskIndex, TaskRecord
from .task_domain import (
    TASK_LINE_PATTERN,
    ParsedTaskItem,
    coerce_task_items,
    normalize_tag_values,
)

SleepFn = Callable[[float], Awaitable[None]]


class ProcessLike(Protocol):
    returncode: int | None

    async def communicate(self) -> tuple[bytes, bytes]: ...
    async def wait(self) -> int: ...


SpawnFn = Callable[..., Awaitable[ProcessLike]]


class ObsidianCommandError(RuntimeError):
    argv: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int | None

    def __init__(
        self,
        argv: Sequence[str],
        stderr: str,
        *,
        stdout: str = "",
        returncode: int | None = None,
    ):
        self.argv = tuple(argv)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        message = stderr.strip() or stdout.strip() or "Obsidian command failed"
        super().__init__(message)


class CommandResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    argv: tuple[str, ...]
    stdout: str
    stderr: str = ""
    returncode: int = 0


@final
class ObsidianCli:
    _settings: Settings
    _spawn: SpawnFn
    _sleep: SleepFn
    _owned_process: ProcessLike | None

    def __init__(
        self,
        settings: Settings,
        *,
        spawn: SpawnFn | None = None,
        sleep: SleepFn | None = None,
    ):
        self._settings = settings
        self._spawn = spawn or cast(SpawnFn, asyncio.create_subprocess_exec)
        self._sleep = sleep or asyncio.sleep
        self._owned_process = None

    async def run_text(self, *args: str) -> str:
        result = await self._run(*args)
        return result.stdout

    async def daily_path(self) -> str:
        output = (await self.run_text("daily:path")).strip()
        return self.normalize_path(output)

    async def daily_read(self) -> str:
        return await self.run_text("daily:read")

    async def read_note(self, path: str) -> str:
        return await self.run_text("read", f"path={path}")

    async def list_markdown_files(self, folder: str) -> list[str]:
        output = await self.run_text("files", f"folder={folder}", "ext=md")
        paths = [
            self.normalize_path(line.strip())
            for line in output.splitlines()
            if line.strip()
        ]
        return sorted(paths)

    async def list_tags(self) -> list[str]:
        output = await self.run_text("tags")
        return sorted(normalize_tag_values(output.splitlines()))

    async def query_tasks(
        self, selector: str, *, path: str | None = None
    ) -> list[TaskRecord]:
        args = ["tasks"]
        if path is not None:
            args.append(f"path={path}")
        args.extend([selector, "verbose", "format=json"])
        output = await self.run_text(*args)
        items = coerce_task_items(output)
        return self._hydrate_task_items(items)

    async def append_daily(self, content: str) -> None:
        _ = await self.run_text("daily:append", f"content={content}")

    async def append_note(self, path: str, content: str) -> None:
        _ = await self.run_text("append", f"path={path}", f"content={content}")

    async def create_note(self, path: str, content: str) -> None:
        _ = await self.run_text("create", f"path={path}", f"content={content}")

    async def mutate_task(self, ref: str, status: str) -> None:
        _ = await self.run_text("task", f"ref={ref}", status)

    def normalize_path(self, value: str) -> str:
        path = Path(value.strip())
        if path.is_absolute():
            return path.relative_to(self._settings.vault_root).as_posix()
        return PurePosixPath(value.strip()).as_posix()

    def resolve_vault_path(self, path: str) -> Path:
        return self._settings.vault_root / PurePosixPath(path)

    def read_vault_text(self, path: str) -> str:
        return self.resolve_vault_path(path).read_text(encoding="utf-8")

    def read_vault_lines(self, path: str) -> list[str]:
        return self.read_vault_text(path).splitlines()

    def snapshot_vault(self) -> dict[str, FileSnapshot]:
        snapshots: dict[str, FileSnapshot] = {}
        for file_path in sorted(self._settings.vault_root.rglob("*.md")):
            relative = file_path.relative_to(self._settings.vault_root).as_posix()
            stat = file_path.stat()
            snapshots[relative] = FileSnapshot(
                size=stat.st_size, mtime_ns=stat.st_mtime_ns
            )
        return snapshots

    def build_open_task_index(self, tasks: list[TaskRecord]) -> TaskIndex:
        open_tasks = tuple(
            sorted(
                (task for task in tasks if task.is_open),
                key=lambda task: (task.path, task.line),
            )
        )
        return TaskIndex(tasks=open_tasks, watched_files=self.snapshot_vault())

    def is_index_current(self, index: TaskIndex) -> bool:
        current = self.snapshot_vault()
        return current == index.watched_files

    def _raise_for_failure(self, result: CommandResult) -> None:
        if result.returncode != 0:
            raise ObsidianCommandError(
                result.argv,
                result.stderr,
                stdout=result.stdout,
                returncode=result.returncode,
            )

    async def _run(self, *args: str) -> CommandResult:
        await self._clear_dead_owned_process()
        if self._owned_process is not None:
            return await self._run_short_lived(*args)

        process = await self._spawn(
            *self._argv(*args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.launch_detection_timeout,
            )
        except TimeoutError:
            self._owned_process = process
            return await self._wait_until_ready(*args)

        result = CommandResult(
            argv=self._argv(*args),
            stdout=stdout_bytes.decode("utf-8"),
            stderr=stderr_bytes.decode("utf-8"),
            returncode=process.returncode or 0,
        )
        self._raise_for_failure(result)
        return result

    async def _run_short_lived(self, *args: str) -> CommandResult:
        process = await self._spawn(
            *self._argv(*args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=self._settings.command_timeout,
        )
        result = CommandResult(
            argv=self._argv(*args),
            stdout=stdout_bytes.decode("utf-8"),
            stderr=stderr_bytes.decode("utf-8"),
            returncode=process.returncode or 0,
        )
        self._raise_for_failure(result)
        return result

    async def _wait_until_ready(self, *args: str) -> CommandResult:
        deadline = time.monotonic() + self._settings.readiness_timeout
        last_error: ObsidianCommandError | None = None

        while time.monotonic() < deadline:
            await self._clear_dead_owned_process()
            if self._owned_process is None:
                return await self._run(*args)
            try:
                return await self._run_short_lived(*args)
            except ObsidianCommandError as exc:
                last_error = exc
                await self._sleep(self._settings.readiness_poll_interval)

        stderr = (
            last_error.stderr
            if last_error is not None
            else "Obsidian did not become ready"
        )
        raise ObsidianCommandError(self._argv(*args), stderr)

    async def _clear_dead_owned_process(self) -> None:
        process = self._owned_process
        if process is None:
            return
        if process.returncode is not None:
            self._owned_process = None
            return
        if await _poll_process(process):
            self._owned_process = None

    def _argv(self, *args: str) -> tuple[str, ...]:
        argv = [self._settings.obsidian_bin]
        if self._settings.vault_selector:
            argv.append(f"vault={self._settings.vault_selector}")
        argv.extend(args)
        return tuple(argv)

    def _hydrate_task_items(self, items: list[ParsedTaskItem]) -> list[TaskRecord]:
        path_lines: dict[str, list[str]] = {}
        tasks: list[TaskRecord] = []
        for item in items:
            lines = path_lines.setdefault(item.path, self.read_vault_lines(item.path))
            if item.line > len(lines):
                raise ValueError(
                    f"Task line {item.line} is out of range for {item.path}"
                )
            raw_line = lines[item.line - 1]
            match = TASK_LINE_PATTERN.match(raw_line)
            if match is None:
                raise ValueError(
                    f"Line {item.line} in {item.path} is not a task line: {raw_line!r}"
                )
            status = item.status or match.group("status")
            tasks.append(
                TaskRecord(
                    path=item.path,
                    line=item.line,
                    text=item.text,
                    status=status,
                    raw_line=raw_line,
                    scheduled_on=item.scheduled_on,
                )
            )
        return tasks


async def _poll_process(process: ProcessLike) -> bool:
    try:
        _ = await asyncio.wait_for(process.wait(), timeout=0)
    except TimeoutError:
        return False
    return True
