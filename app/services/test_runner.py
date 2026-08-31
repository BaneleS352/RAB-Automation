"""Run the pytest test suite in a subprocess and summarize the results."""

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TestRunResult:
    success: bool = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    output: str = ""
    timed_out: bool = False
    message: str = ""
    tests: list[dict] = field(default_factory=list)


_TEST_LINE_RE = re.compile(
    r"^(tests/.*?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)(?:\s+\[.*\])?$"
)


def _parse_tests(output: str) -> list[dict]:
    """Extract per-test results from pytest -v output."""
    tests = []
    for line in output.splitlines():
        m = _TEST_LINE_RE.match(line.strip())
        if m:
            tests.append({"nodeid": m.group(1), "status": m.group(2)})
    return tests


def _count(text: str, word: str) -> int:
    m = re.search(r"\b(\d+)\s+" + re.escape(word) + r"\b", text)
    return int(m.group(1)) if m else 0


def _parse_summary(output: str) -> tuple[int, int, int, int, float]:
    lines = [ln for ln in output.splitlines() if ln.strip()]
    summary = next(
        (ln for ln in reversed(lines) if any(
            w in ln for w in ("passed", "failed", "errors", "skipped", "deselected")
        )),
        "",
    )
    passed = _count(summary, "passed")
    failed = _count(summary, "failed")
    errors = _count(summary, "errors")
    skipped = _count(summary, "skipped")
    duration = 0.0
    m = re.search(r"in ([0-9.]+)s", summary)
    if m:
        duration = float(m.group(1))
    return passed, failed, errors, skipped, duration


def _tail(output: str, max_lines: int = 150) -> str:
    lines = output.splitlines()
    if len(lines) <= max_lines:
        return output
    return "...\n" + "\n".join(lines[-max_lines:])


def _run_blocking(
    cmd: list[str], env: dict, cwd: str, timeout: int
) -> subprocess.CompletedProcess:
    """Run pytest synchronously. Executed in a worker thread via to_thread.

    Uses subprocess.run (not asyncio subprocess) because uvicorn's default
    event loop on Windows (SelectorEventLoop) does not support subprocess.
    """
    return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)


async def run_test_suite(timeout: int = 120) -> TestRunResult:
    """Run the full pytest suite in a subprocess.

    The subprocess gets an isolated SQLite path via DATABASE_PATH so running
    tests does not touch the live application database.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    temp_db = Path(tempfile.gettempdir()) / f"rab_test_{os.getpid()}_{uuid.uuid4().hex[:8]}.db"

    env = dict(os.environ)
    env["APP_ENV"] = "test"
    env["DATABASE_PATH"] = str(temp_db)

    cmd = [
        sys.executable, "-m", "pytest",
        "-v", "--tb=short", "--no-header", "-p", "no:cacheprovider",
    ]

    try:
        process = await asyncio.to_thread(
            _run_blocking, cmd, env, str(project_root), timeout
        )
    except subprocess.TimeoutExpired:
        # Clean up temp DB even on timeout
        for p in [temp_db, Path(str(temp_db) + "-shm"), Path(str(temp_db) + "-wal")]:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return TestRunResult(
            timed_out=True,
            output=f"Test run exceeded {timeout}s and was terminated.",
            message=f"Timed out after {timeout}s",
        )
    except OSError as e:
        logger.error("Failed to launch pytest subprocess: %s", e)
        for p in [temp_db, Path(str(temp_db) + "-shm"), Path(str(temp_db) + "-wal")]:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return TestRunResult(success=False, message=f"Failed to launch pytest: {e}")

    output = process.stdout + process.stderr
    passed, failed, errors, skipped, duration = _parse_summary(output)
    tests = _parse_tests(output)

    result = TestRunResult(
        success=(failed == 0 and errors == 0),
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_seconds=duration,
        output=_tail(output),
        message=f"Exit code {process.returncode}",
        tests=tests,
    )
    # Clean up isolated DB — previously leaked (C10)
    for p in [temp_db, Path(str(temp_db) + "-shm"), Path(str(temp_db) + "-wal")]:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    return result
