from __future__ import annotations

from lmnop.handler.models import TaskRecord, assign_task_ids


def test_assign_task_ids_numbers_collisions_in_source_order() -> None:
    tasks = [
        TaskRecord(
            path="a.md",
            line=1,
            text="duplicate",
            status=" ",
            raw_line="- [ ] duplicate",
        ),
        TaskRecord(
            path="a.md",
            line=2,
            text="duplicate",
            status=" ",
            raw_line="- [ ] duplicate",
        ),
        TaskRecord(
            path="a.md", line=3, text="changed", status=" ", raw_line="- [ ] changed"
        ),
        TaskRecord(
            path="b.md",
            line=1,
            text="duplicate",
            status=" ",
            raw_line="- [ ] duplicate",
        ),
    ]

    ids = assign_task_ids(tasks)
    duplicate_ids = [
        task_id for task_id, task in ids.items() if task.text == "duplicate"
    ]
    assert duplicate_ids[0].endswith("")
    assert duplicate_ids[1].endswith("-1")


def test_assign_task_ids_changes_when_path_or_text_changes() -> None:
    original = TaskRecord(
        path="a.md", line=1, text="task", status=" ", raw_line="- [ ] task"
    )
    moved = TaskRecord(
        path="b.md", line=1, text="task", status=" ", raw_line="- [ ] task"
    )
    edited = TaskRecord(
        path="a.md",
        line=1,
        text="task edited",
        status=" ",
        raw_line="- [ ] task edited",
    )

    assert original.base_id != moved.base_id
    assert original.base_id != edited.base_id
