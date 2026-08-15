#!/usr/bin/env python3
"""Boot xv6, run shell commands, retain a transcript, and enforce PASS output."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import re
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
        transcript.write(f"# CPUS={args.cpus} timeout={args.timeout}\n")
        transcript.write(f"# commands={args.commands!r}\n")
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
