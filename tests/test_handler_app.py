from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from lmnop.handler.server import HandlerApplication
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

    asyncio.run(run())


def test_append_daily_returns_new_task_ids(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        result = await app.append("client", "daily", "- [ ] Plan the trip")
        target_path = result.target_path
        new_tasks = result.new_tasks
        assert target_path.startswith("journals/")
        assert list(new_tasks.values()) == ["Plan the trip"]
        note_text = cli.read_vault_text(target_path)
        assert "- [ ] Plan the trip" in note_text

    asyncio.run(run())


def test_append_project_creates_missing_note_and_preserves_nested_items(
    tmp_path: Path,
) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        result = await app.append(
            "client",
            "voice-assistant",
            "parent\n  * [ ] child task",
        )
        assert result.target_path == "notes/projects/voice-assistant/.minutes.md"
        note_text = cli.read_vault_text("notes/projects/voice-assistant/.minutes.md")
        assert "- parent" in note_text
        assert "  * [ ] child task" in note_text
        new_tasks = result.new_tasks
        assert list(new_tasks.values()) == ["child task"]

    asyncio.run(run())


def test_append_rejects_project_path_traversal(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)

    async def run() -> None:
        try:
            _ = await app.append("client", "../../etc", "- [ ] nope")
        except ValueError as exc:
            assert "single relative path segment" in str(exc)
        else:
            raise AssertionError("Expected invalid project target to fail")

    asyncio.run(run())


def test_resolve_done_and_dropped_update_source_in_place(tmp_path: Path) -> None:
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
        done_result = await app.resolve("client", today_id, "done")
        dropped_result = await app.resolve("client", dropped_id, "dropped")
        assert done_result.new_id is None
        assert dropped_result.new_id is None
        assert "- [x] Overdue project task" in cli.read_vault_text(
            "notes/projects/eavesdrop/.minutes.md"
        )
        assert "- [-] Old unscheduled note" in cli.read_vault_text(
            paths["two_days_ago"]
        )

    asyncio.run(run())


def test_resolve_carries_task_forward_and_refreshes_stale_cache(tmp_path: Path) -> None:
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
            _ = await app.resolve("client", carry_id, "carried")
        except ValueError as exc:
            assert "Unknown open task id" in str(exc)
        else:
            raise AssertionError(
                "Expected stale id resolution to fail after cache refresh"
            )

        refreshed = await app.daily_standup("client")
        renamed_id = next(
            line.split(":", 1)[0]
            for line in refreshed.splitlines()
            if "Fresh inbox item renamed" in line
        )
        result = await app.resolve("client", renamed_id, "carried")
        assert result.new_id is not None
        today_text = cli.read_vault_text(await cli.daily_path())
        assert "- [ ] Fresh inbox item renamed" in today_text
        updated_yesterday = cli.read_vault_text(paths["yesterday"])
        assert "- [>] Fresh inbox item renamed" in updated_yesterday

    asyncio.run(run())
