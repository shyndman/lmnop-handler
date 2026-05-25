from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

PROJECT_MINUTES_PREFIX = Path("notes/projects")


class FileSnapshot(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    size: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class TaskRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str
    line: int = Field(ge=1)
    text: str
    status: str = Field(min_length=1, max_length=1)
    raw_line: str
    scheduled_on: date | None = None

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.line}"

    @property
    def base_id(self) -> str:
        digest = sha256(f"{self.path}: {self.text}".encode("utf-8")).hexdigest()
        return digest[:4]

    @property
    def is_open(self) -> bool:
        return self.status not in {"x", "X", "-", ">"}

    @property
    def project(self) -> str | None:
        path = Path(self.path)
        parts = path.parts
        prefix = PROJECT_MINUTES_PREFIX.parts
        if (
            len(parts) == len(prefix) + 2
            and parts[: len(prefix)] == prefix
            and parts[-1] == ".minutes.md"
        ):
            return parts[len(prefix)]
        return None

    @property
    def source_label(self) -> str:
        project = self.project
        if project is not None:
            return f"Project: {project}"
        return f"Note: {self.path}"


class TaskIndex(BaseModel):
    tasks: tuple[TaskRecord, ...]
    watched_files: dict[str, FileSnapshot]

    @property
    def by_id(self) -> dict[str, TaskRecord]:
        return assign_task_ids(self.tasks)

    def replace_paths(
        self,
        paths: set[str],
        replacements: list[TaskRecord],
        watched_files: Mapping[str, FileSnapshot],
    ) -> TaskIndex:
        kept = [task for task in self.tasks if task.path not in paths]
        kept.extend(replacements)
        kept.sort(key=lambda task: (task.path, task.line, task.text, task.status))
        return TaskIndex(tasks=tuple(kept), watched_files=dict(watched_files))


class AppendResult(BaseModel):
    success: bool = True
    target_path: str
    new_tasks: dict[str, str]


class TaskStatusResult(BaseModel):
    success: bool = True
    id: str
    text: str
    status: str


class NoteSection(BaseModel):
    title: str
    what: str
    why: str
    groups: list[tuple[str, str]]


def assign_task_ids(
    tasks: tuple[TaskRecord, ...] | list[TaskRecord],
) -> dict[str, TaskRecord]:
    grouped: dict[str, list[TaskRecord]] = defaultdict(list)
    ordered = sorted(
        tasks, key=lambda task: (task.path, task.line, task.text, task.status)
    )
    for task in ordered:
        grouped[task.base_id].append(task)

    ids: dict[str, TaskRecord] = {}
    for base_id, group in grouped.items():
        for index, task in enumerate(group):
            task_id = base_id if index == 0 else f"{base_id}-{index}"
            ids[task_id] = task
    return ids
