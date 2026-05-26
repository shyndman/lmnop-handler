from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)

if TYPE_CHECKING:
    from .models import TaskRecord

TASK_LINE_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<bullet>[-*+])\s+\[(?P<status>[^\]])\]\s+(?P<text>.*)$"
)
LIST_LINE_PATTERN = re.compile(r"^(?P<indent>\s*)(?P<bullet>[-*+])\s+(?P<text>.*)$")
SCHEDULED_PATTERN = re.compile(r"⏳\s*(\d{4}-\d{2}-\d{2})")
TAG_PATTERN = re.compile(r"(?<![\w/])#(?P<tag>[A-Za-z0-9_/-]+)")
TASK_QUERY_SELECTORS = ("todo", "done", "status=-", "status=>")
DONE_TASK_STATUSES = frozenset({"x", "X"})
CLOSED_TASK_STATUSES = frozenset({"x", "X", "-", ">"})


@dataclass(frozen=True, slots=True)
class TaskStatusRule:
    symbol: str
    label: str
    mutation: str
    closes_task: bool
    usage: str | None = None
    examples: tuple[str, ...] = ()


TOOL_STATUS_RULES = (
    TaskStatusRule(" ", "open/default", "status= ", False),
    TaskStatusRule("x", "done", "done", True),
    TaskStatusRule("-", "dropped/cancelled", "status=-", True),
    TaskStatusRule(
        ">",
        "carried forward",
        "status=>",
        True,
        "match only when carrying an old task forward; use append_note separately for the new task wording.",
    ),
    TaskStatusRule(
        "!",
        "attention required",
        "status=!",
        False,
        "only when the user explicitly says the task needs attention, care, judgment, or discussion.",
        (
            '"this one needs attention"',
            '"be careful with this one"',
            '"this needs a decision before acting"',
        ),
    ),
    TaskStatusRule(
        "/",
        "in progress",
        "status=/",
        False,
        "only when work has actually started.",
        (
            '"I started this"',
            '"I am halfway through"',
            '"continue working on this"',
            '"pick this back up"',
        ),
    ),
    TaskStatusRule(
        "?",
        "question",
        "status=?",
        False,
        "only when the deliverable is an answer.",
        (
            '"question:"',
            '"answer this"',
            '"find out whether"',
            '"decide whether"',
            '"I need to know whether"',
        ),
    ),
    TaskStatusRule(
        "*",
        "agent task",
        "status=*",
        False,
        "only for tasks assigned to the agent.",
        (
            '"agent task"',
            '"for the agent"',
            '"you take this"',
            '"this one is yours"',
        ),
    ),
)
TOOL_TASK_STATUSES = frozenset(rule.symbol for rule in TOOL_STATUS_RULES)
_TASK_STATUS_RULE_BY_SYMBOL = {rule.symbol: rule for rule in TOOL_STATUS_RULES}
_TASK_STATUS_SYMBOL_BY_MUTATION = {
    rule.mutation: rule.symbol for rule in TOOL_STATUS_RULES
}

TaskScheduleBucket = Literal["today_focus", "upcoming", "later"]


class ParsedTaskItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str
    line: int = Field(ge=1)
    text: str
    status: str | None = Field(default=None, min_length=1, max_length=1)
    scheduled_on: date | None = None

    @field_validator("line", mode="before")
    @classmethod
    def validate_line(cls, value: object) -> object:
        if isinstance(value, str):
            return int(value)
        return value


class ListLine(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    indent: int = Field(ge=0)
    is_task: bool


class RawTaskPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    path: str = Field(validation_alias=AliasChoices("path", "file"))
    line: int = Field(ge=1)
    text: str = Field(validation_alias=AliasChoices("text", "task", "content", "body"))
    status: str | None = Field(
        default=None,
        min_length=1,
        max_length=1,
        validation_alias=AliasChoices(
            "status", "status_char", "statusCharacter", "marker"
        ),
    )
    scheduled_on: date | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "scheduled",
            "scheduled_date",
            "scheduledDate",
            "scheduled_on",
            "scheduledOn",
        ),
    )

    @field_validator("line", mode="before")
    @classmethod
    def validate_raw_line(cls, value: object) -> object:
        if isinstance(value, str):
            return int(value)
        return value


class TaskPayloadEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    tasks: list[RawTaskPayload]


_TASK_PAYLOAD_ADAPTER: TypeAdapter[list[RawTaskPayload] | TaskPayloadEnvelope] = (
    TypeAdapter(list[RawTaskPayload] | TaskPayloadEnvelope)
)


def is_open_task_status(status: str) -> bool:
    return status not in CLOSED_TASK_STATUSES


def is_done_task_status(status: str) -> bool:
    return status in DONE_TASK_STATUSES


def matches_task_selector(task: TaskRecord, selector: str) -> bool:
    if selector == "todo":
        return is_open_task_status(task.status)
    if selector == "done":
        return is_done_task_status(task.status)
    if selector == "status=-":
        return task.status == "-"
    if selector == "status=>":
        return task.status == ">"
    raise ValueError(f"Unsupported selector: {selector}")


def tool_status_display(symbol: str) -> str:
    return f"[{symbol}]" if symbol != " " else "[ ]"


def tool_status_summary() -> str:
    return ", ".join(
        f"{tool_status_display(rule.symbol)} {rule.label}" for rule in TOOL_STATUS_RULES
    )


def tool_status_guidance_lines() -> list[str]:
    lines = [
        "10. "
        + " ".join(
            f"Use {tool_status_display(rule.symbol)} {rule.usage}"
            for rule in TOOL_STATUS_RULES
            if rule.usage is not None and rule.symbol in {"!", "/", "?", "*"}
        )
    ]
    lines.append("Status examples:")
    for rule in TOOL_STATUS_RULES:
        if not rule.examples:
            continue
        joined = ", ".join(rule.examples)
        lines.append(f"- {tool_status_display(rule.symbol)} match: {joined}.")
    carry_rule = _TASK_STATUS_RULE_BY_SYMBOL[">"]
    assert carry_rule.usage is not None
    lines.append(f"- {tool_status_display(carry_rule.symbol)} {carry_rule.usage}")
    return lines


def normalize_list_content(content: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in content.splitlines():
        if not raw_line.strip():
            normalized_lines.append(raw_line)
            continue
        if LIST_LINE_PATTERN.match(raw_line):
            normalized_lines.append(raw_line)
            continue
        indent_length = len(raw_line) - len(raw_line.lstrip())
        normalized_lines.append(f"{raw_line[:indent_length]}- {raw_line.lstrip()}")
    if not normalized_lines:
        return ""
    return "\n".join(normalized_lines)


def normalize_tag_values(values: Iterable[str]) -> set[str]:
    tags: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        tag = stripped if stripped.startswith("#") else f"#{stripped}"
        tags.add(tag)
    return tags


def render_note_block(note_text: str, target_lines: dict[int, str]) -> str:
    lines = note_text.splitlines()
    included: set[int] = set(target_lines)
    for line_number in target_lines:
        current_indent = _line_indent(lines[line_number - 1])
        for index in range(line_number - 2, -1, -1):
            parsed = parse_list_line(lines[index])
            if parsed is None:
                continue
            if parsed.indent < current_indent:
                included.add(index + 1)
                current_indent = parsed.indent
                if current_indent == 0:
                    break

    rendered: list[str] = []
    for index, line in enumerate(lines, start=1):
        if index not in included:
            continue
        prefix = target_lines.get(index, "____")
        rendered.append(f"{prefix}: {line}")
    return "\n".join(rendered)


def render_recent_notes(note_text: str) -> str:
    lines = note_text.splitlines()
    selected = {
        index: "____"
        for index, line in enumerate(lines, start=1)
        if (parsed := parse_list_line(line)) is not None and not parsed.is_task
    }
    if not selected:
        return ""
    return render_note_block(note_text, selected)


def parse_list_line(line: str) -> ListLine | None:
    task_match = TASK_LINE_PATTERN.match(line)
    if task_match is not None:
        return ListLine(indent=len(task_match.group("indent")), is_task=True)
    list_match = LIST_LINE_PATTERN.match(line)
    if list_match is None:
        return None
    return ListLine(indent=len(list_match.group("indent")), is_task=False)


def parse_task_records(path: str, note_text: str) -> list[TaskRecord]:
    from .models import TaskRecord

    tasks: list[TaskRecord] = []
    for index, raw_line in enumerate(note_text.splitlines(), start=1):
        match = TASK_LINE_PATTERN.match(raw_line)
        if match is None:
            continue
        text = match.group("text")
        tasks.append(
            TaskRecord(
                path=path,
                line=index,
                text=text,
                status=match.group("status"),
                raw_line=raw_line,
                scheduled_on=_scheduled_from_text(text),
            )
        )
    return tasks


def task_ids_for_file(tasks: list[TaskRecord], path: str) -> dict[int, str]:
    from .models import TaskIndex

    ids = TaskIndex(
        tasks=tuple(sorted(tasks, key=lambda task: (task.path, task.line))),
        watched_files={},
    ).by_id
    return {task.line: task_id for task_id, task in ids.items() if task.path == path}


def classify_schedule(
    task: TaskRecord, today: date, upcoming_days: int
) -> TaskScheduleBucket | None:
    if task.scheduled_on is None:
        return None
    if task.scheduled_on <= today:
        return "today_focus"
    if task.scheduled_on <= today + timedelta(days=upcoming_days):
        return "upcoming"
    return "later"


def task_status_mutation(status: str) -> str:
    rule = _TASK_STATUS_RULE_BY_SYMBOL.get(status)
    if rule is None:
        raise ValueError(f"Unsupported task status: {status}")
    return rule.mutation


def task_status_from_mutation(mutation: str) -> str:
    status = _TASK_STATUS_SYMBOL_BY_MUTATION.get(mutation)
    if status is None:
        raise ValueError(f"Unsupported task status mutation: {mutation}")
    return status


def stripped_task_body(raw_line: str) -> str:
    match = TASK_LINE_PATTERN.match(raw_line)
    if match is None:
        raise ValueError(f"Not a task line: {raw_line!r}")
    return match.group("text")


def coerce_task_items(payload: object) -> list[ParsedTaskItem]:
    if isinstance(payload, str) and payload.strip() in {"", "No tasks found."}:
        return []
    parsed = (
        _TASK_PAYLOAD_ADAPTER.validate_json(payload)
        if isinstance(payload, str)
        else _TASK_PAYLOAD_ADAPTER.validate_python(payload)
    )
    raw_items = parsed if isinstance(parsed, list) else parsed.tasks
    return [
        ParsedTaskItem(
            path=item.path,
            line=item.line,
            text=item.text,
            status=item.status,
            scheduled_on=item.scheduled_on or _scheduled_from_text(item.text),
        )
        for item in raw_items
    ]


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _scheduled_from_text(text: str) -> date | None:
    match = SCHEDULED_PATTERN.search(text)
    if match is None:
        return None
    return date.fromisoformat(match.group(1))
