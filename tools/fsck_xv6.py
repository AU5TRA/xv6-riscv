#!/usr/bin/env python3
"""Offline consistency and block-leak checker for an xv6 fs.img.

The kernel offers no way to read the free-block count from user space, so a
"no block leak" claim has to be checked from the host. This walks every
allocated inode (direct, singly-indirect and doubly-indirect), builds the set
of blocks that are actually reachable, and compares it against the on-disk
free bitmap.

A leaked block is one the bitmap marks as allocated that no inode references.
A missing block is one an inode references that the bitmap marks as free --
that is worse, because balloc will hand it out a second time.

Usage:
    python3 tools/fsck_xv6.py fs.img [--fssize 100000] [--verbose]

Exit status is 0 only when the image is fully consistent.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

BSIZE = 1024
FSMAGIC = 0x10203040
NDIRECT = 11
NINDIRECT = BSIZE // 4
NDINDIRECT = NINDIRECT * NINDIRECT
MAXFILE = NDIRECT + NINDIRECT + NDINDIRECT
DINODE_SIZE = 64
IPB = BSIZE // DINODE_SIZE
BPB = BSIZE * 8

T_DIR = 1
T_FILE = 2
T_DEVICE = 3
TYPE_NAMES = {0: "free", T_DIR: "dir", T_FILE: "file", T_DEVICE: "dev"}


class Image:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        self.path = path

    def block(self, bn: int) -> bytes:
        off = bn * BSIZE
        if off + BSIZE > len(self.data):
            raise IndexError(f"block {bn} past end of {self.path}")
        return self.data[off : off + BSIZE]

    def words(self, bn: int) -> tuple[int, ...]:
        return struct.unpack_from(f"<{NINDIRECT}I", self.block(bn))


class Superblock:
    FIELDS = (
        "magic",
        "size",
        "nblocks",
        "ninodes",
        "nlog",
        "logstart",
        "inodestart",
        "bmapstart",
    )

    def __init__(self, raw: bytes):
        values = struct.unpack_from("<8I", raw)
        for name, value in zip(self.FIELDS, values):
            setattr(self, name, value)

    def __str__(self) -> str:
        return " ".join(f"{n}={getattr(self, n)}" for n in self.FIELDS[1:])


class Dinode:
    def __init__(self, raw: bytes):
        (
            self.type,
            self.major,
            self.minor,
            self.nlink,
            self.size,
        ) = struct.unpack_from("<4hI", raw)
        self.addrs = struct.unpack_from("<13I", raw, 12)


class Checker:
    def __init__(self, image: Image, expect_fssize: int | None, verbose: bool):
        self.img = image
        self.expect_fssize = expect_fssize
        self.verbose = verbose
        self.errors: list[str] = []
        self.notes: list[str] = []
        # block number -> short description of the first owner seen
        self.owner: dict[int, str] = {}

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def claim(self, bn: int, who: str) -> None:
        """Record that `who` references block `bn`; flag double references."""
        if bn in self.owner:
            self.error(f"block {bn} referenced twice: {self.owner[bn]} and {who}")
            return
        self.owner[bn] = who

    # ---------------------------------------------------------------- walk --
    def walk_inode(self, inum: int, din: Dinode) -> None:
        who = f"inode {inum} ({TYPE_NAMES.get(din.type, din.type)})"
        if din.type == T_DEVICE:
            return  # device inodes hold no data blocks

        need = (din.size + BSIZE - 1) // BSIZE
        if need > MAXFILE:
            self.error(f"{who}: size {din.size} needs {need} blocks > MAXFILE {MAXFILE}")

        seen = 0

        for i in range(NDIRECT):
            addr = din.addrs[i]
            if addr:
                self.check_range(addr, f"{who} direct[{i}]")
                self.claim(addr, f"{who} direct[{i}]")
                seen = max(seen, i + 1)

        sind = din.addrs[NDIRECT]
        if sind:
            self.check_range(sind, f"{who} indirect block")
            self.claim(sind, f"{who} indirect block")
            for j, addr in enumerate(self.img.words(sind)):
                if addr:
                    self.check_range(addr, f"{who} indirect[{j}]")
                    self.claim(addr, f"{who} indirect[{j}]")
                    seen = max(seen, NDIRECT + j + 1)

        dind = din.addrs[NDIRECT + 1]
        if dind:
            self.check_range(dind, f"{who} doubly-indirect block")
            self.claim(dind, f"{who} doubly-indirect block")
            for l1, l1addr in enumerate(self.img.words(dind)):
                if not l1addr:
                    continue
                self.check_range(l1addr, f"{who} doubly-indirect[{l1}]")
                self.claim(l1addr, f"{who} doubly-indirect[{l1}]")
                for l2, addr in enumerate(self.img.words(l1addr)):
                    if addr:
                        self.check_range(addr, f"{who} doubly-indirect[{l1}][{l2}]")
                        self.claim(addr, f"{who} doubly-indirect[{l1}][{l2}]")
                        seen = max(
                            seen, NDIRECT + NINDIRECT + l1 * NINDIRECT + l2 + 1
                        )

        if seen < need:
            # A block covered by the size but not mapped would read as a hole,
            # which xv6's write path never produces.
            self.error(
                f"{who}: size {din.size} covers {need} blocks but only {seen} "
                f"are mapped"
            )
        elif seen > need:
            # Legitimate: writei calls bmap before copying, so a write that
            # faults on its source address leaves a mapped block past the
            # size. Those blocks are still reachable, so they are not leaks.
            self.notes.append(
                f"{who}: {seen - need} block(s) mapped past the size "
                f"{din.size} (a write that failed after bmap)"
            )

        if self.verbose and din.type:
            print(
                f"  inode {inum:4d} {TYPE_NAMES.get(din.type, din.type):4s} "
                f"nlink={din.nlink} size={din.size} blocks={need}"
            )

    def check_range(self, bn: int, who: str) -> None:
        if bn < self.nmeta or bn >= self.sb.size:
            self.error(f"{who}: block {bn} outside data region [{self.nmeta}, {self.sb.size})")

    # ---------------------------------------------------------------- main --
    def run(self) -> int:
        self.sb = Superblock(self.img.block(1))
        if self.sb.magic != FSMAGIC:
            print(f"FAIL: bad superblock magic {self.sb.magic:#x}", file=sys.stderr)
            return 1

        nbitmap = self.sb.size // BPB + 1
        self.nmeta = self.sb.bmapstart + nbitmap
        print(f"superblock: {self.sb}")
        print(f"derived:    nbitmap={nbitmap} nmeta={self.nmeta} maxfile={MAXFILE}")

        if self.expect_fssize is not None and self.sb.size != self.expect_fssize:
            self.error(f"sb.size {self.sb.size} != expected FSSIZE {self.expect_fssize}")

        if self.sb.size * BSIZE > len(self.img.data):
            self.error(
                f"image is {len(self.img.data)} bytes, smaller than "
                f"sb.size {self.sb.size} blocks"
            )

        # An unclean stop can leave an uninstalled transaction in the log.
        log_n = struct.unpack_from("<I", self.img.block(self.sb.logstart))[0]
        if log_n != 0:
            self.notes.append(
                f"log header holds {log_n} uninstalled blocks; the numbers below "
                f"predate that transaction"
            )

        # Reserved metadata is always allocated.
        for bn in range(self.nmeta):
            self.owner[bn] = "metadata"

        inodes = 0
        for inum in range(self.sb.ninodes):
            raw = self.img.block(self.sb.inodestart + inum // IPB)
            din = Dinode(raw[(inum % IPB) * DINODE_SIZE :])
            if din.type == 0:
                continue
            if inum == 0:
                self.error("inode 0 is allocated but must stay unused")
            inodes += 1
            self.walk_inode(inum, din)
        print(f"inodes:     {inodes} allocated of {self.sb.ninodes}")

        used = set()
        for bn in range(0, self.sb.size, BPB):
            blk = self.img.block(self.sb.bmapstart + bn // BPB)
            limit = min(BPB, self.sb.size - bn)
            for bi in range(limit):
                if blk[bi // 8] & (1 << (bi % 8)):
                    used.add(bn + bi)

        reachable = set(self.owner)
        leaked = sorted(used - reachable)
        missing = sorted(reachable - used)

        print(f"blocks:     {len(used)} marked used, {len(reachable)} reachable, "
              f"{self.sb.size - len(used)} free")

        if leaked:
            self.error(
                f"{len(leaked)} leaked block(s) marked used but unreachable: "
                f"{leaked[:16]}{' ...' if len(leaked) > 16 else ''}"
            )
        if missing:
            self.error(
                f"{len(missing)} block(s) referenced but marked free: "
                f"{missing[:16]}{' ...' if len(missing) > 16 else ''}"
            )

        for note in self.notes:
            print(f"note: {note}")

        if self.errors:
            print(f"\nFAIL: {len(self.errors)} problem(s)", file=sys.stderr)
            for err in self.errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

        print("\nPASS: no leaked blocks, no double references, no missing blocks")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path, nargs="?", default=Path("fs.img"))
    ap.add_argument(
        "--fssize", type=int, default=None, help="assert sb.size equals this"
    )
    ap.add_argument("--verbose", action="store_true", help="list every inode")
    args = ap.parse_args()

    if not args.image.exists():
        print(f"no such image: {args.image}", file=sys.stderr)
        return 1
    return Checker(Image(args.image), args.fssize, args.verbose).run()


if __name__ == "__main__":
    raise SystemExit(main())
