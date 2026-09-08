#!/usr/bin/env python3
"""Boot xv6, run shell commands, retain a transcript, and enforce PASS output."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import re
import subprocess
import sys
import time

try:
    import pexpect
except ImportError as exc:
    raise SystemExit(
        "pexpect is required (on Debian/Ubuntu: python3-pexpect)"
    ) from exc


PROMPT = re.compile(r"\$ ")
FATAL = re.compile(
    r"panic:|SOME TESTS FAILED|FAILED --|(?:vmtest|prefetchtest): [^\r\n]+: FAIL|(?:^|\r?\n)exec .* failed\r?\n",
    re.MULTILINE,
)


def pass_marker(command: str) -> re.Pattern[str]:
    parts = command.strip().split()
    program = parts[0] if parts else ""
    if program == "usertests":
        return re.compile(r"ALL TESTS PASSED")
    if program == "vmtest":
        name = re.escape(parts[1]) if len(parts) > 1 else r"[^\r\n]+"
        return re.compile(rf"vmtest: {name}: PASS")
    if program == "prefetchtest":
        name = re.escape(parts[1]) if len(parts) > 1 else r"[^\r\n]+"
        return re.compile(rf"prefetchtest: {name}: PASS")
    return re.compile(r"(?:^|\r?\n)PASS(?:\r?\n|$)")


def safe_name(commands: list[str]) -> str:
    joined = "_".join(commands)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", joined).strip("-")
    return (name or "xv6")[:100]


def remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("test timeout expired")
    return left


def terminate(child: pexpect.spawn) -> None:
    if not child.isalive():
        return
    child.send("\x01x")
    try:
        child.expect(pexpect.EOF, timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF):
        child.terminate(force=True)


def tool_version(command: list[str]) -> str:
    """First line of a --version banner, or a marker if the tool is absent."""
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0] if text else "unavailable"


def provenance(repo: Path, args: argparse.Namespace) -> list[str]:
    """Everything Phase 2 acceptance criterion 15 requires on the host side.

    The guest prints its own compile-time configuration at boot (see
    kernel/main.c:vm_print_config). This covers what the guest cannot know:
    which commit, which toolchain, whether the tree was dirty, and which
    build configuration the harness asked for. A transcript is only usable
    as evidence if it carries both halves.
    """
    # core.autocrlf is forced on for every query. The worktree is checked
    # out by Windows Git with CRLF conversion, so a Linux Git that does not
    # apply the same conversion reports all 104 tracked text files as
    # modified. That is not a dirty tree, it is a line-ending mismatch, and
    # a provenance header that cried "dirty" on every run would be ignored
    # exactly when it mattered.
    def git(*a: str) -> str:
        try:
            out = subprocess.run(
                ["git", "-c", "core.autocrlf=true", "-C", str(repo), *a],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
        return out.stdout.strip() or ""

    def count(text: str) -> int:
        return len(text.splitlines()) if text else 0

    modified = git("diff", "--name-only", "HEAD")
    untracked = git("ls-files", "--others", "--exclude-standard")
    lines = [
        f"# date={dt.datetime.now().isoformat(timespec='seconds')}",
        f"# commit={git('rev-parse', 'HEAD') or 'unavailable'}",
        f"# describe={git('describe', '--tags', '--always', '--dirty') or 'unavailable'}",
        f"# worktree=modified({count(modified)}) untracked({count(untracked)})",
        f"# cpus={args.cpus} timeout={args.timeout}",
        f"# vm_debug={os.environ.get('VM_DEBUG', '0')}",
        f"# cc={tool_version(['riscv64-unknown-elf-gcc', '--version'])}",
        f"# qemu={tool_version([args.qemu or 'qemu-system-riscv64', '--version'])}",
        f"# python={sys.version.split()[0]}",
        f"# host={tool_version(['uname', '-srm'])}",
        f"# commands={args.commands!r}",
    ]
    return lines


def run(args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parents[1]
    logs = repo / "test-logs"
    logs.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_path = logs / f"{stamp}-{safe_name(args.commands)}.log"
    deadline = time.monotonic() + args.timeout
    child: pexpect.spawn | None = None

    env = os.environ.copy()
    make_args = ["qemu", f"CPUS={args.cpus}"]
    if args.qemu:
        make_args.append(f"QEMU={args.qemu}")

    with log_path.open("w", encoding="utf-8", errors="replace") as transcript:
        for line in provenance(repo, args):
            transcript.write(line + "\n")
        transcript.flush()
        try:
            child = pexpect.spawn(
                "make",
                make_args,
                cwd=str(repo),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=min(60, remaining(deadline)),
            )
            child.logfile_read = transcript
            index = child.expect([PROMPT, FATAL, pexpect.TIMEOUT, pexpect.EOF])
            if index != 0:
                raise RuntimeError("xv6 did not reach its shell prompt")

            for command in args.commands:
                marker = pass_marker(command)
                transcript.write(f"\n# RUN {command}\n")
                transcript.flush()
                child.sendline(command)
                child.timeout = remaining(deadline)
                index = child.expect(
                    [marker, FATAL, PROMPT, pexpect.TIMEOUT, pexpect.EOF]
                )
                if index == 1:
                    raise RuntimeError(f"failure output while running {command!r}")
                if index == 2:
                    raise RuntimeError(
                        f"command returned without PASS marker: {command!r}"
                    )
                if index == 3:
                    raise TimeoutError(f"timeout while running {command!r}")
                if index == 4:
                    raise RuntimeError(f"QEMU exited while running {command!r}")

                child.timeout = min(30, remaining(deadline))
                index = child.expect([PROMPT, FATAL, pexpect.TIMEOUT, pexpect.EOF])
                if index != 0:
                    raise RuntimeError(
                        f"xv6 did not return to its prompt after {command!r}"
                    )

            transcript.write("\n# RESULT PASS\n")
            print(f"PASS: {log_path}")
            return 0
        except (RuntimeError, TimeoutError, pexpect.ExceptionPexpect) as exc:
            transcript.write(f"\n# RESULT FAIL: {exc}\n")
            print(f"FAIL: {exc}; transcript: {log_path}", file=sys.stderr)
            return 1
        finally:
            if child is not None:
                terminate(child)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpus", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--qemu", help="qemu-system-riscv64 path (otherwise use QEMU/PATH)"
    )
    parser.add_argument("commands", nargs="+")
    args = parser.parse_args()
    if args.cpus < 1 or args.timeout <= 0:
        parser.error("--cpus and --timeout must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
