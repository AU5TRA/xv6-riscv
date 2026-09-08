#!/usr/bin/env python3
"""Copy a file out of an xv6 fs.img on the host.

A trace drained by user/vmdrain.c lands inside the guest filesystem, and xv6
has no way to hand it to the host. This walks the root directory and the
inode's block map -- direct, singly-indirect and doubly-indirect -- and writes
the bytes out.

Usage:
    python3 tools/extract_file.py fs.img trace.bin out/trace.bin
    python3 tools/extract_file.py fs.img --list
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
DINODE_SIZE = 64
IPB = BSIZE // DINODE_SIZE
ROOTINO = 1
DIRSIZ = 14
DIRENT_SIZE = 16
T_DIR = 1
T_FILE = 2


class Image:
    def __init__(self, path: Path):
        self.blob = path.read_bytes()
        self.path = path
        sb = struct.unpack_from("<8I", self.blob, BSIZE)
        (
            self.magic,
            self.size,
            self.nblocks,
            self.ninodes,
            self.nlog,
            self.logstart,
            self.inodestart,
            self.bmapstart,
        ) = sb
        if self.magic != FSMAGIC:
            raise SystemExit(f"{path}: bad superblock magic {self.magic:#x}")

    def block(self, bn: int) -> bytes:
        off = bn * BSIZE
        if bn == 0 or off + BSIZE > len(self.blob):
            raise SystemExit(f"{self.path}: block {bn} out of range")
        return self.blob[off : off + BSIZE]

    def pointers(self, bn: int) -> tuple[int, ...]:
        return struct.unpack_from(f"<{NINDIRECT}I", self.block(bn))

    def inode(self, inum: int) -> tuple[int, int, int]:
        """Returns (type, size, addrs) for an inode number."""
        blk = self.block(self.inodestart + inum // IPB)
        base = (inum % IPB) * DINODE_SIZE
        itype, _major, _minor, _nlink = struct.unpack_from("<4h", blk, base)
        (size,) = struct.unpack_from("<I", blk, base + 8)
        addrs = struct.unpack_from("<13I", blk, base + 12)
        return itype, size, addrs

    def block_of(self, addrs: tuple[int, ...], bn: int) -> int:
        """Mirror of bmap() in kernel/fs.c, read-only. 0 means a hole."""
        if bn < NDIRECT:
            return addrs[bn]
        bn -= NDIRECT
        if bn < NINDIRECT:
            root = addrs[NDIRECT]
            return self.pointers(root)[bn] if root else 0
        bn -= NINDIRECT
        root = addrs[NDIRECT + 1]
        if not root:
            return 0
        level1 = self.pointers(root)[bn // NINDIRECT]
        if not level1:
            return 0
        return self.pointers(level1)[bn % NINDIRECT]

    def read_file(self, inum: int) -> bytes:
        itype, size, addrs = self.inode(inum)
        if itype != T_FILE:
            raise SystemExit(f"inode {inum} is type {itype}, not a regular file")
        out = bytearray()
        remaining = size
        bn = 0
        while remaining > 0:
            addr = self.block_of(addrs, bn)
            take = min(remaining, BSIZE)
            out += bytes(take) if addr == 0 else self.block(addr)[:take]
            remaining -= take
            bn += 1
        return bytes(out)

    def root_entries(self):
        itype, size, addrs = self.inode(ROOTINO)
        if itype != T_DIR:
            raise SystemExit("root inode is not a directory")
        for off in range(0, size, DIRENT_SIZE):
            addr = self.block_of(addrs, off // BSIZE)
            if addr == 0:
                continue
            raw = self.block(addr)[off % BSIZE : off % BSIZE + DIRENT_SIZE]
            (inum,) = struct.unpack_from("<H", raw)
            if inum == 0:
                continue
            name = raw[2 : 2 + DIRSIZ].split(b"\0")[0].decode("ascii", "replace")
            yield name, inum


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("name", nargs="?", help="file name in the xv6 root directory")
    ap.add_argument("output", nargs="?", type=Path)
    ap.add_argument("--list", action="store_true", help="list the root directory")
    args = ap.parse_args()

    if not args.image.exists():
        print(f"no such image: {args.image}", file=sys.stderr)
        return 1
    img = Image(args.image)

    if args.list or not args.name:
        for name, inum in img.root_entries():
            itype, size, _ = img.inode(inum)
            kind = {T_DIR: "dir", T_FILE: "file"}.get(itype, str(itype))
            print(f"{inum:4d} {kind:<5} {size:>12} {name}")
        return 0

    for name, inum in img.root_entries():
        if name == args.name:
            data = img.read_file(inum)
            out = args.output or Path(args.name)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            print(f"extracted {args.name} ({len(data)} bytes) -> {out}")
            return 0

    print(f"{args.name}: not found in {args.image}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
