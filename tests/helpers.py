from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path, PurePosixPath

from lmnop.handler.config import Settings
from lmnop.handler.models import FileSnapshot, TaskIndex, TaskRecord
from lmnop.handler.task_domain import (
    TAG_PATTERN,
    TASK_LINE_PATTERN,
    matches_task_selector,
    normalize_tag_values,
    parse_task_records,
    task_status_from_mutation,
)


class FakeObsidianCli:
    settings: Settings
    today: date

    def __init__(self, settings: Settings, today: date | None = None):
        self.settings = settings
        self.today = today or date.today()

    async def daily_path(self) -> str:
        return f"journals/{self.today.isoformat()}.md"

    async def daily_read(self) -> str:
        return self.read_vault_text(await self.daily_path())

    async def read_note(self, path: str) -> str:
        return self.read_vault_text(path)

    async def list_markdown_files(self, folder: str) -> list[str]:
        folder_path = self.resolve_vault_path(folder)
        if not folder_path.exists():
            return []
        return sorted(
            file_path.relative_to(self.settings.vault_root).as_posix()
            for file_path in folder_path.glob("*.md")
        )

    async def list_tags(self) -> list[str]:
        raw_tags: list[str] = []
        for path in self._all_markdown_paths():
            for match in TAG_PATTERN.finditer(self.read_vault_text(path)):
                raw_tags.append(match.group("tag"))
        return sorted(normalize_tag_values(raw_tags))

    async def query_tasks(
        self, selector: str, *, path: str | None = None
    ) -> list[TaskRecord]:
        paths = [path] if path is not None else self._all_markdown_paths()
        tasks: list[TaskRecord] = []
        for relative_path in paths:
            tasks.extend(self._parse_tasks(relative_path))
        return [task for task in tasks if matches_task_selector(task, selector)]

    async def append_daily(self, content: str) -> None:
        await self.append_note(await self.daily_path(), content)

    async def append_note(self, path: str, content: str) -> None:
        note_path = self.resolve_vault_path(path)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        chunk = content if content.endswith("\n") else f"{content}\n"
        if existing and not existing.endswith("\n"):
            existing = f"{existing}\n"
        _ = note_path.write_text(f"{existing}{chunk}", encoding="utf-8")

    async def create_note(self, path: str, content: str) -> None:
        note_path = self.resolve_vault_path(path)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        chunk = content if content.endswith("\n") else f"{content}\n"
        _ = note_path.write_text(chunk, encoding="utf-8")

    async def mutate_task(self, ref: str, status: str) -> None:
        path, raw_line = ref.rsplit(":", 1)
        line_number = int(raw_line)
        lines = self.read_vault_lines(path)
        line = lines[line_number - 1]
        match = TASK_LINE_PATTERN.match(line)
        if match is None:
            raise ValueError(f"Not a task line: {ref}")
        new_status = task_status_from_mutation(status)
        lines[line_number - 1] = (
            f"{match.group('indent')}{match.group('bullet')} [{new_status}] {match.group('text')}"
        )
        _ = self.resolve_vault_path(path).write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def normalize_path(self, value: str) -> str:
        path = Path(value.strip())
        if path.is_absolute():
            return path.relative_to(self.settings.vault_root).as_posix()
        return PurePosixPath(value.strip()).as_posix()

    def resolve_vault_path(self, path: str) -> Path:
        return self.settings.vault_root / PurePosixPath(path)

    def read_vault_text(self, path: str) -> str:
        return self.resolve_vault_path(path).read_text(encoding="utf-8")

    def read_vault_lines(self, path: str) -> list[str]:
        return self.read_vault_text(path).splitlines()

    def snapshot_vault(self) -> dict[str, FileSnapshot]:
        snapshots: dict[str, FileSnapshot] = {}
        for file_path in sorted(self.settings.vault_root.rglob("*.md")):
            relative = file_path.relative_to(self.settings.vault_root).as_posix()
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
        return self.snapshot_vault() == index.watched_files

    def _all_markdown_paths(self) -> list[str]:
        return sorted(
            file_path.relative_to(self.settings.vault_root).as_posix()
            for file_path in self.settings.vault_root.rglob("*.md")
        )

    def _parse_tasks(self, path: str) -> list[TaskRecord]:
        note_path = self.resolve_vault_path(path)
        if not note_path.exists():
            return []
        return parse_task_records(path, note_path.read_text(encoding="utf-8"))


def make_settings(vault_root: Path) -> Settings:
    return Settings(
        vault_root=vault_root,
        vault_selector="test",
    )


def seed_vault(vault_root: Path, today: date | None = None) -> dict[str, str]:
    current = today or date.today()
    yesterday = current - timedelta(days=1)
    two_days_ago = current - timedelta(days=2)
    soon = current + timedelta(days=3)
    far = current + timedelta(days=30)

    (vault_root / "journals").mkdir(parents=True, exist_ok=True)
    (vault_root / "notes/projects/eavesdrop").mkdir(parents=True, exist_ok=True)

    today_path = vault_root / "journals" / f"{current.isoformat()}.md"
    yesterday_path = vault_root / "journals" / f"{yesterday.isoformat()}.md"
    two_days_ago_path = vault_root / "journals" / f"{two_days_ago.isoformat()}.md"
    project_path = vault_root / "notes/projects/eavesdrop/.minutes.md"

    _ = today_path.write_text(
        "- [ ] Existing today task\n",
        encoding="utf-8",
    )
    _ = yesterday_path.write_text(
        "".join(
            [
                "* Found this really great tool, Langfuse https://langfuse.ai\n",
                f"  * [ ] Throw it on the NAS and kick the tires ⏳ {current.isoformat()}\n",
                "- [ ] Fresh inbox item\n",
                f"- [ ] Someday idea ⏳ {far.isoformat()}\n",
                "- [x] Wrapped something up\n",
                "- [-] Decided not to do something\n",
            ]
        ),
        encoding="utf-8",
    )
    _ = two_days_ago_path.write_text(
        "".join(
            [
                "- [ ] Old unscheduled note\n",
                "- Mentioned cache invalidation concerns\n",
            ]
        ),
        encoding="utf-8",
    )
    _ = project_path.write_text(
        "".join(
            [
                f"- [ ] Prepare migration notes ⏳ {soon.isoformat()}\n",
                f"- [ ] Overdue project task ⏳ {yesterday.isoformat()}\n",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "today": today_path.relative_to(vault_root).as_posix(),
        "yesterday": yesterday_path.relative_to(vault_root).as_posix(),
        "two_days_ago": two_days_ago_path.relative_to(vault_root).as_posix(),
        "project": project_path.relative_to(vault_root).as_posix(),
    }
