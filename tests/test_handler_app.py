from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from lmnop.handler.application import HandlerApplication
from tests.helpers import FakeObsidianCli, make_settings, seed_vault

FIXTURE_VAULT = Path("tests/vault/handler-test-vault")


def test_daily_standup_renders_markdown_sections(tmp_path: Path) -> None:
    paths = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        assert "# Daily Standup" in briefing
        assert f"Current date: {date.today().isoformat()}." in briefing
        assert "## Today focus" in briefing
        assert "## Upcoming" in briefing
        assert "## Recent unscheduled" in briefing
        assert "## Recent resolutions" in briefing
        assert "## Recent notes" in briefing
        assert "Throw it on the NAS and kick the tires" in briefing
        assert "Someday idea" not in briefing
        assert "Prepare migration notes" in briefing
        assert "____: * Found this really great tool" in briefing
        assert paths["yesterday"] in briefing
        assert "Project: eavesdrop" in briefing
        assert "set_task_status only changes the existing checkbox status" in briefing
        assert "- [!] match:" in briefing
        assert "- [/] match:" in briefing
        assert "- [?] match:" in briefing
        assert "- [*] match:" in briefing

    asyncio.run(run())


def test_daily_standup_handles_empty_recent_history(tmp_path: Path) -> None:
    today_path = tmp_path / "journals" / f"{date.today().isoformat()}.md"
    today_path.parent.mkdir(parents=True, exist_ok=True)
    _ = today_path.write_text("- [ ] Existing today task\n", encoding="utf-8")
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        assert "## Recent unscheduled" in briefing
        assert (
            "### Note:"
            not in briefing.split("## Recent unscheduled", 1)[1].split(
                "## Recent resolutions", 1
            )[0]
        )

    asyncio.run(run())


def test_daily_standup_reads_repo_fixture_vault() -> None:
    settings = make_settings(FIXTURE_VAULT)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        assert "Throw it on the NAS and kick the tires" in briefing
        assert "Prepare migration notes" in briefing
        assert f"Current date: {date.today().isoformat()}." in briefing

    asyncio.run(run())


def test_daily_standup_includes_project_tags(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    _ = (tmp_path / "journals" / "project-tags.md").write_text(
        "- #project/zulu note\n- #project/alpha note\n- #area/home note\n",
        encoding="utf-8",
    )
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        project_guidance = " ".join(
            [
                "When a note has to do with a project, it MUST be marked",
                "with the matching #project/ tag.",
            ]
        )
        assert project_guidance in briefing
        assert "   - #project/alpha\n   - #project/zulu" in briefing
        assert "#area/home" not in briefing

    asyncio.run(run())


def test_append_daily_returns_new_task_ids(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        result = await app.append("client", "- [ ] Plan the trip\nRemember passport")
        target_path = result.target_path
        new_tasks = result.new_tasks
        assert target_path.startswith("journals/")
        assert list(new_tasks.values()) == ["Plan the trip"]
        note_text = cli.read_vault_text(target_path)
        assert "- [ ] Plan the trip" in note_text
        assert "- Remember passport" in note_text
        assert "\nRemember passport" not in note_text

    asyncio.run(run())


def test_append_daily_preserves_nested_items_and_returns_new_task_ids(
    tmp_path: Path,
) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        result = await app.append(
            "client",
            "parent\n  child context\n  * [ ] child task",
        )
        assert result.target_path.startswith("journals/")
        note_text = cli.read_vault_text(result.target_path)
        assert "- parent" in note_text
        assert "  - child context" in note_text
        assert "\n  child context" not in note_text
        assert "  * [ ] child task" in note_text
        new_tasks = result.new_tasks
        assert list(new_tasks.values()) == ["child task"]

    asyncio.run(run())


def test_resolve_statuses_update_source_in_place(tmp_path: Path) -> None:
    paths = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        today_id = next(
            line.split(":", 1)[0]
            for line in briefing.splitlines()
            if "Overdue project task" in line
        )
        dropped_id = next(
            line.split(":", 1)[0]
            for line in briefing.splitlines()
            if "Old unscheduled note" in line
        )
        done_result = await app.set_task_status("client", today_id, "x")
        dropped_result = await app.set_task_status("client", dropped_id, "-")
        assert done_result.status == "x"
        assert dropped_result.status == "-"
        assert "- [x] Overdue project task" in cli.read_vault_text(
            "notes/projects/eavesdrop/.minutes.md"
        )
        assert "- [-] Old unscheduled note" in cli.read_vault_text(
            paths["two_days_ago"]
        )

    asyncio.run(run())


def test_resolve_carried_status_refreshes_stale_cache(tmp_path: Path) -> None:
    paths = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        carry_id = next(
            line.split(":", 1)[0]
            for line in briefing.splitlines()
            if "Fresh inbox item" in line
        )
        yesterday_path = tmp_path / Path(paths["yesterday"])
        yesterday_text = yesterday_path.read_text(encoding="utf-8")
        _ = yesterday_path.write_text(
            yesterday_text.replace("Fresh inbox item", "Fresh inbox item renamed"),
            encoding="utf-8",
        )
        try:
            _ = await app.set_task_status("client", carry_id, ">")
        except ValueError as exc:
            assert "Unknown open task id" in str(exc)
        else:
            raise AssertionError(
                "Expected stale id status update to fail after cache refresh"
            )

        refreshed = await app.daily_standup("client")
        renamed_id = next(
            line.split(":", 1)[0]
            for line in refreshed.splitlines()
            if "Fresh inbox item renamed" in line
        )
        result = await app.set_task_status("client", renamed_id, ">")
        assert result.status == ">"
        today_text = cli.read_vault_text(await cli.daily_path())
        assert "- [ ] Fresh inbox item renamed" not in today_text
        updated_yesterday = cli.read_vault_text(paths["yesterday"])
        assert "- [>] Fresh inbox item renamed" in updated_yesterday

    asyncio.run(run())


def test_set_task_status_decorative_open_status_stays_open(tmp_path: Path) -> None:
    paths = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        briefing = await app.daily_standup("client")
        task_id = next(
            line.split(":", 1)[0]
            for line in briefing.splitlines()
            if "Fresh inbox item" in line
        )
        result = await app.set_task_status("client", task_id, "!")
        assert result.status == "!"
        assert "- [!] Fresh inbox item" in cli.read_vault_text(paths["yesterday"])

        refreshed = await app.daily_standup("client")
        assert "Fresh inbox item" in refreshed.split("## Recent unscheduled", 1)[1]
        reset_id = next(
            line.split(":", 1)[0]
            for line in refreshed.splitlines()
            if "Fresh inbox item" in line
        )
        reset_result = await app.set_task_status("client", reset_id, " ")
        assert reset_result.status == " "
        assert "- [ ] Fresh inbox item" in cli.read_vault_text(paths["yesterday"])

        star_briefing = await app.daily_standup("client")
        star_id = next(
            line.split(":", 1)[0]
            for line in star_briefing.splitlines()
            if "Fresh inbox item" in line
        )
        star_result = await app.set_task_status("client", star_id, "*")
        assert star_result.status == "*"
        assert "- [*] Fresh inbox item" in cli.read_vault_text(paths["yesterday"])

    asyncio.run(run())
