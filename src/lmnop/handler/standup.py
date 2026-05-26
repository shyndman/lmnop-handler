from __future__ import annotations

from datetime import date
from textwrap import dedent

from .models import StandupSection
from .task_domain import tool_status_guidance_lines, tool_status_summary

_STANDUP_WORKFLOW_LINES = dedent(
    """\
    # Daily Standup

    This is the authoritative briefing for today's standup. Use it to conduct the conversation.

    Workflow:
    1. Work through Today focus first.
    2. Review Upcoming for near-term preparation.
    3. For each Recent unscheduled item, ask whether it is still real. If done use set_task_status status x; if dropped use -; if carried forward use >.
    4. set_task_status only changes the existing checkbox status. If a carried task needs new wording, dates, or scope, also use append_note to create the new active task.
    5. Review Recent resolutions and Recent notes for continuity.
    6. Capture notes with append_note as bullets or nested bullets.
    7. When a note has to do with a project, it MUST be marked with the matching #project/ tag.
    8. Available project tags:
    """
).splitlines()
_TASK_EMOJI_GUIDANCE_LINES = dedent(
    """\
    Task emoji syntax (from docs/emoji_task_format.md):
    - Dates: ➕ created, ⏳ scheduled, 🛫 start, 📅 due, ✅ done, ❌ cancelled; all dates use YYYY-MM-DD.
    - Priorities: ⏬ lowest, 🔽 low, no marker normal, 🔼 medium, ⏫ high, 🔺 highest.
    - Recurrence: 🔁 followed by the rule, e.g. 🔁 every day when done.
    - On completion: 🏁 keep or 🏁 delete.
    - Dependencies: 🆔 task-id defines an id; ⛔ id1,id2 blocks on ids.
    - Daily-note placement alone does not make a task due today or active today; use an explicit 📅, ⏳, or 🛫 date marker.
    """
).splitlines()


def render_standup_markdown(
    today: date, sections: list[StandupSection], project_tags: list[str]
) -> str:
    lines = [
        _STANDUP_WORKFLOW_LINES[0],
        "",
        f"Current date: {today.isoformat()}.",
        *_STANDUP_WORKFLOW_LINES[2:],
        *(f"   - {tag}" for tag in project_tags),
        f"9. Supported task statuses: {tool_status_summary()}. Pass the exact single status character to set_task_status.",
        *tool_status_guidance_lines(),
        "",
        *_TASK_EMOJI_GUIDANCE_LINES,
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
