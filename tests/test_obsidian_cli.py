from __future__ import annotations

import asyncio
from pathlib import Path
from typing import final

from lmnop.handler.config import Settings
from lmnop.handler.obsidian import ObsidianCli


@final
class FakeProcess:
    returncode: int | None
    _stdout: bytes
    _stderr: bytes
    _hangs: bool

    def __init__(
        self,
        *,
        returncode: int | None,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hangs: bool = False,
    ):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hangs = hangs

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hangs:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        if self.returncode is None:
            await asyncio.sleep(3600)
        assert self.returncode is not None
        return self.returncode


async def _spawn_factory(
    processes: list[FakeProcess],
    *args: str,
    stdout: int | None,
    stderr: int | None,
) -> FakeProcess:
    _ = args, stdout, stderr
    return processes.pop(0)


def test_cli_retries_after_launch_detection(tmp_path: Path) -> None:
    processes = [
        FakeProcess(returncode=None, hangs=True),
        FakeProcess(returncode=0, stdout=b"ready\n"),
    ]
    settings = Settings(
        vault_root=tmp_path,
        bearer_tokens={"client": "secret"},
        launch_detection_timeout=0.01,
        readiness_timeout=0.1,
        readiness_poll_interval=0.01,
    )

    async def spawn(*args: str, stdout: int | None, stderr: int | None) -> FakeProcess:
        return await _spawn_factory(processes, *args, stdout=stdout, stderr=stderr)

    cli = ObsidianCli(settings, spawn=spawn)

    async def run() -> None:
        assert await cli.run_text("daily:path") == "ready\n"

    asyncio.run(run())


def test_cli_reuses_short_lived_calls_when_owned_process_is_alive(
    tmp_path: Path,
) -> None:
    processes = [
        FakeProcess(returncode=None, hangs=True),
        FakeProcess(returncode=0, stdout=b"ready\n"),
        FakeProcess(returncode=0, stdout=b"second\n"),
    ]
    settings = Settings(
        vault_root=tmp_path,
        bearer_tokens={"client": "secret"},
        launch_detection_timeout=0.01,
        readiness_timeout=0.1,
        readiness_poll_interval=0.01,
    )

    async def spawn(*args: str, stdout: int | None, stderr: int | None) -> FakeProcess:
        return await _spawn_factory(processes, *args, stdout=stdout, stderr=stderr)

    cli = ObsidianCli(settings, spawn=spawn)

    async def run() -> None:
        assert await cli.run_text("daily:path") == "ready\n"
        assert await cli.run_text("daily:path") == "second\n"

    asyncio.run(run())
