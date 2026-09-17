#!/usr/bin/env python3
"""Decode a paging trace captured by user/vmdrain.c.

Capture layout (see user/vmdrain.c):

    [ struct vmtrace_header : 128 bytes ][ struct vmtrace_event : 64 bytes ] * n

The header describes the schema. Completeness is proved from the records: the
kernel stamps every emitted event with a monotonic sequence number and resets
sequencing when the ring is reset, so a capture is lossless exactly when

  * the first record has sequence 1,
  * every subsequent sequence is exactly one greater than its predecessor, and
  * no record carries type VMTRACE_DROP.

A capture that fails any of those is *invalid*, not merely suspect: a model
trained on a trace with silent holes learns from a biased sample with nothing
flagging it. This exits non-zero in that case, and `--strict` additionally
refuses to emit any decoded output.

Usage:
    python3 tools/decode_trace.py trace.bin                    # validate + summary
    python3 tools/decode_trace.py trace.bin --csv out.csv      # decode to CSV
    python3 tools/decode_trace.py trace.bin --jsonl out.jsonl  # decode to JSONL
    python3 tools/decode_trace.py trace.bin --head 20          # print records
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

VMTRACE_VERSION = 3
HEADER_SIZE = 128
RECORD_SIZE = 64

# Must match enum vmtrace_type in kernel/vmtrace.h.
TYPE_NAMES = {
    1: "ZERO_FAULT",
    2: "SWAP_FAULT",
    3: "PROTECTION_FAULT",
    4: "MAP",
    5: "UNMAP",
    6: "VICTIM_SELECTED",
    7: "EVICT_BEGIN",
    8: "EVICT_END",
    9: "SWAP_READ_BEGIN",
    10: "SWAP_READ_END",
    11: "SWAP_WRITE_BEGIN",
    12: "SWAP_WRITE_END",
    13: "PREFETCH_HINT",
    14: "PREFETCH_QUEUE",
    15: "PREFETCH_BEGIN",
    16: "PREFETCH_END",
    17: "PREFETCH_USE",
    18: "PREFETCH_WASTE",
    19: "PREFETCH_CANCEL",
    20: "POLICY_FALLBACK",
    21: "DROP",
}
DROP_TYPE = 21

# Must match kernel/vmpage.h.
PAGE_STATE_NAMES = {
    0: "FREE",
    1: "RESIDENT_DEMAND",
    2: "RESIDENT_PREFETCH",
    3: "EVICTING",
}
ACCESS_NAMES = {0: "READ", 1: "WRITE", 2: "EXEC"}
POLICY_NAMES = {0: "FIFO", 1: "CLOCK", 2: "AGING"}

HEADER_FIELDS = (
    "version",
    "record_size",
    "capacity",
    "read_max",
    "sequence",
    "dropped",
    "buffered",
    "enabled",
    "event_mask",
    "reserved0",
    "reserved1",
    "reserved2",
    "reserved3",
    "reserved4",
    "reserved5",
    "reserved6",
)
HEADER_STRUCT = struct.Struct("<16Q")

# uint64 sequence, uint64 cycle, uint32 ticks, generation, pid, vpn,
# victim_vpn, frame_index, swap_slot, resident_count, queue_id,
# int32 status, uint16 pte_flags, uint8 type, access, page_state, policy,
# uint8 reserved[2]
RECORD_STRUCT = struct.Struct("<QQ9IiH4B2x")
RECORD_FIELDS = (
    "sequence",
    "cycle",
    "ticks",
    "generation",
    "pid",
    "vpn",
    "victim_vpn",
    "frame_index",
    "swap_slot",
    "resident_count",
    "queue_id",
    "status",
    "pte_flags",
    "type",
    "access",
    "page_state",
    "policy",
)

NONE32 = 0xFFFFFFFF
NONE16 = 0xFFFF
NONE8 = 0xFF

# Column order for CSV/JSONL output.
COLUMNS = (
    "sequence",
    "cycle",
    "ticks",
    "pid",
    "generation",
    "type",
    "type_name",
    "vpn",
    "access",
    "access_name",
    "page_state",
    "page_state_name",
    "pte_flags",
    "frame_index",
    "swap_slot",
    "policy",
    "policy_name",
    "victim_vpn",
    "queue_id",
    "resident_count",
    "status",
)


def sentinel(value: int, none: int):
    """Map an all-ones field to None."""
    return None if value == none else value


def decode_header(blob: bytes) -> dict:
    return dict(zip(HEADER_FIELDS, HEADER_STRUCT.unpack(blob)))


def decode_record(blob: bytes) -> dict:
    raw = dict(zip(RECORD_FIELDS, RECORD_STRUCT.unpack(blob)))
    out = {
        "sequence": raw["sequence"],
        "cycle": raw["cycle"],
        "ticks": raw["ticks"],
        "pid": sentinel(raw["pid"], NONE32),
        "generation": sentinel(raw["generation"], NONE32),
        "type": raw["type"],
        "type_name": TYPE_NAMES.get(raw["type"], f"UNKNOWN_{raw['type']}"),
        "vpn": sentinel(raw["vpn"], NONE32),
        "victim_vpn": sentinel(raw["victim_vpn"], NONE32),
        "frame_index": sentinel(raw["frame_index"], NONE32),
        "swap_slot": sentinel(raw["swap_slot"], NONE32),
        "resident_count": sentinel(raw["resident_count"], NONE32),
        "queue_id": sentinel(raw["queue_id"], NONE32),
        "status": raw["status"],
        "pte_flags": sentinel(raw["pte_flags"], NONE16),
    }
    access = sentinel(raw["access"], NONE8)
    state = sentinel(raw["page_state"], NONE8)
    policy = sentinel(raw["policy"], NONE8)
    out["access"] = access
    out["access_name"] = ACCESS_NAMES.get(access) if access is not None else None
    out["page_state"] = state
    out["page_state_name"] = (
        PAGE_STATE_NAMES.get(state) if state is not None else None
    )
    out["policy"] = policy
    out["policy_name"] = POLICY_NAMES.get(policy) if policy is not None else None
    return out


class Capture:
    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size
        self.errors: list[str] = []

        if self.size < HEADER_SIZE:
            raise SystemExit(f"{path}: {self.size} bytes is smaller than a header")

        with path.open("rb") as fh:
            self.header = decode_header(fh.read(HEADER_SIZE))

        if self.header["version"] != VMTRACE_VERSION:
            self.errors.append(
                f"header version {self.header['version']} != {VMTRACE_VERSION}"
            )
        if self.header["record_size"] != RECORD_SIZE:
            self.errors.append(
                f"header record_size {self.header['record_size']} != {RECORD_SIZE}"
            )

        body = self.size - HEADER_SIZE
        self.count = body // RECORD_SIZE
        if body % RECORD_SIZE:
            self.errors.append(
                f"{body} record bytes is not a multiple of {RECORD_SIZE}; "
                f"the capture is misaligned or truncated mid-record"
            )

    def records(self):
        """Streams decoded records, validating sequencing as it goes."""
        previous = None
        drops = 0
        gaps = 0
        types: dict[str, int] = {}
        pids: dict[int | None, int] = {}
        first = None
        last = None

        with self.path.open("rb") as fh:
            fh.seek(HEADER_SIZE)
            for index in range(self.count):
                blob = fh.read(RECORD_SIZE)
                if len(blob) != RECORD_SIZE:
                    self.errors.append(f"short read at record {index}")
                    break
                rec = decode_record(blob)

                if rec["type"] == DROP_TYPE:
                    drops += 1
                if previous is None:
                    if rec["sequence"] != 1:
                        self.errors.append(
                            f"first record has sequence {rec['sequence']}, not 1: "
                            f"the capture starts after events were already lost"
                        )
                    first = rec["sequence"]
                elif rec["sequence"] != previous + 1:
                    gaps += 1
                    if gaps <= 8:
                        self.errors.append(
                            f"sequence gap at record {index}: "
                            f"{previous} -> {rec['sequence']} "
                            f"({rec['sequence'] - previous - 1} lost)"
                        )
                previous = rec["sequence"]
                last = rec["sequence"]

                types[rec["type_name"]] = types.get(rec["type_name"], 0) + 1
                pids[rec["pid"]] = pids.get(rec["pid"], 0) + 1
                yield rec

        if gaps > 8:
            self.errors.append(f"... {gaps - 8} further sequence gap(s) not listed")
        if drops:
            self.errors.append(f"{drops} in-band DROP record(s): the ring overran")

        self.stats = {
            "drops": drops,
            "gaps": gaps,
            "types": types,
            "pids": pids,
            "first_sequence": first,
            "last_sequence": last,
        }


def summarise(cap: Capture) -> None:
    header = cap.header
    print(f"file:      {cap.path} ({cap.size} bytes)")
    print(
        f"header:    version={header['version']} record_size={header['record_size']} "
        f"capacity={header['capacity']} read_max={header['read_max']} "
        f"event_mask={header['event_mask']:#x}"
    )
    print(f"records:   {cap.count}")
    stats = cap.stats
    print(
        f"sequence:  {stats['first_sequence']}..{stats['last_sequence']} "
        f"gaps={stats['gaps']} drop_records={stats['drops']}"
    )
    if stats["last_sequence"] and stats["first_sequence"]:
        expected = stats["last_sequence"] - stats["first_sequence"] + 1
        print(f"coverage:  {cap.count} of {expected} sequence numbers present")
    print("by pid:    " + ", ".join(
        f"{pid}:{n}" for pid, n in sorted(
            stats["pids"].items(), key=lambda kv: -kv[1])[:8]))
    print("by type:")
    for name, n in sorted(stats["types"].items(), key=lambda kv: -kv[1]):
        print(f"  {name:<18} {n}")


def encode_record(fields: dict) -> bytes:
    """Inverse of decode_record, for the round-trip self-test."""
    return RECORD_STRUCT.pack(
        fields["sequence"],
        fields["cycle"],
        fields["ticks"],
        fields["generation"],
        fields["pid"],
        fields["vpn"],
        fields["victim_vpn"],
        fields["frame_index"],
        fields["swap_slot"],
        fields["resident_count"],
        fields["queue_id"],
        fields["status"],
        fields["pte_flags"],
        fields["type"],
        fields["access"],
        fields["page_state"],
        fields["policy"],
    )


def synthetic(index: int) -> dict:
    """A record whose every field varies with the index, so a decoder that
    mixes two fields up or slips by a byte cannot produce matching output."""
    seq = index + 1
    return {
        "sequence": seq,
        "cycle": 0x1122334455660000 + seq,
        "ticks": (seq * 7) & 0xFFFFFFFF,
        "generation": seq % 4096,
        "pid": 3 + (seq % 61),
        "vpn": (seq * 13) & 0x00FFFFFF,
        "victim_vpn": NONE32 if seq % 5 else (seq * 17) & 0x00FFFFFF,
        "frame_index": NONE32 if seq % 7 == 0 else seq % 32768,
        "swap_slot": NONE32 if seq % 3 == 0 else seq % 8192,
        "resident_count": seq % 1024,
        "queue_id": NONE32 if seq % 11 else seq,
        "status": -1 if seq % 9 == 0 else 0,
        "pte_flags": NONE16 if seq % 13 == 0 else (seq % 0x400),
        "type": 1 + (seq % 20),  # never DROP (21)
        "access": NONE8 if seq % 4 == 0 else seq % 3,
        "page_state": NONE8 if seq % 6 == 0 else seq % 4,
        "policy": NONE8 if seq % 8 == 0 else seq % 3,
    }


def selftest(count: int, tmp: Path) -> int:
    """Round-trips `count` synthetic records through the on-disk format, then
    checks that deliberate corruption is reported rather than tolerated."""
    print(f"selftest: writing {count} synthetic records to {tmp}")
    header = HEADER_STRUCT.pack(
        VMTRACE_VERSION, RECORD_SIZE, 262144, 256, count, 0, 0, 1,
        (1 << 64) - 1, 0, 0, 0, 0, 0, 0, 0,
    )
    with tmp.open("wb") as fh:
        fh.write(header)
        chunk = bytearray()
        for i in range(count):
            chunk += encode_record(synthetic(i))
            if len(chunk) >= 1 << 20:
                fh.write(chunk)
                chunk = bytearray()
        if chunk:
            fh.write(chunk)

    cap = Capture(tmp)
    if cap.count != count:
        print(f"selftest: FAIL: decoded {cap.count} records, expected {count}",
              file=sys.stderr)
        return 1

    checked = 0
    for index, got in enumerate(cap.records()):
        want = synthetic(index)
        for name, raw in want.items():
            expect = raw
            if name in ("pid", "generation", "vpn", "victim_vpn", "frame_index",
                        "swap_slot", "resident_count", "queue_id"):
                expect = None if raw == NONE32 else raw
            elif name == "pte_flags":
                expect = None if raw == NONE16 else raw
            elif name in ("access", "page_state", "policy"):
                expect = None if raw == NONE8 else raw
            if got[name] != expect:
                print(
                    f"selftest: FAIL: record {index} field {name}: "
                    f"decoded {got[name]!r}, expected {expect!r}",
                    file=sys.stderr,
                )
                return 1
        checked += 1
    if checked != count or cap.errors:
        print(f"selftest: FAIL: checked {checked}, errors {cap.errors}",
              file=sys.stderr)
        return 1
    print(f"selftest: {checked} records round-tripped exactly, no gaps reported")

    # A capture with a hole must be rejected, or the drop discipline is
    # unenforceable.
    holed = tmp.with_suffix(".holed")
    blob = tmp.read_bytes()
    cut = HEADER_SIZE + (count // 2) * RECORD_SIZE
    holed.write_bytes(blob[:cut] + blob[cut + RECORD_SIZE:])
    hcap = Capture(holed)
    for _ in hcap.records():
        pass
    if not hcap.errors:
        print("selftest: FAIL: a removed record was not detected", file=sys.stderr)
        return 1
    print(f"selftest: removing one record was detected ({hcap.errors[0]})")

    # So must a capture truncated mid-record.
    ragged = tmp.with_suffix(".ragged")
    ragged.write_bytes(blob[:-17])
    rcap = Capture(ragged)
    for _ in rcap.records():
        pass
    if not rcap.errors:
        print("selftest: FAIL: a mid-record truncation was not detected",
              file=sys.stderr)
        return 1
    print(f"selftest: misalignment was detected ({rcap.errors[0]})")

    holed.unlink()
    ragged.unlink()
    print("\nPASS: decoder round-trips exactly and rejects incomplete captures")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", type=Path)
    ap.add_argument("--csv", type=Path, help="write decoded records as CSV")
    ap.add_argument("--jsonl", type=Path, help="write decoded records as JSONL")
    ap.add_argument("--head", type=int, default=0, help="print the first N records")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="write no output at all if the capture lost records",
    )
    ap.add_argument(
        "--selftest",
        type=int,
        metavar="N",
        help="generate N synthetic records at CAPTURE and verify the "
        "round-trip, then verify that a hole and a misalignment are caught",
    )
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.selftest, args.capture)

    if not args.capture.exists():
        print(f"no such capture: {args.capture}", file=sys.stderr)
        return 1

    cap = Capture(args.capture)

    # A strict run validates first, then decodes, so nothing downstream ever
    # sees records from an incomplete capture.
    if args.strict:
        for _ in cap.records():
            pass
        if cap.errors:
            summarise(cap)
            print(f"\nINVALID: {len(cap.errors)} problem(s)", file=sys.stderr)
            for err in cap.errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    csv_writer = None
    csv_file = None
    jsonl_file = None
    if args.csv:
        csv_file = args.csv.open("w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=list(COLUMNS))
        csv_writer.writeheader()
    if args.jsonl:
        jsonl_file = args.jsonl.open("w", encoding="utf-8")

    printed = 0
    for rec in cap.records():
        if csv_writer:
            csv_writer.writerow({k: rec[k] for k in COLUMNS})
        if jsonl_file:
            jsonl_file.write(json.dumps({k: rec[k] for k in COLUMNS}) + "\n")
        if printed < args.head:
            print(
                f"  #{rec['sequence']:<8} {rec['type_name']:<18} "
                f"pid={rec['pid']} vpn={rec['vpn']} frame={rec['frame_index']} "
                f"slot={rec['swap_slot']} victim={rec['victim_vpn']} "
                f"resident={rec['resident_count']} status={rec['status']}"
            )
            printed += 1

    if csv_file:
        csv_file.close()
        print(f"wrote {args.csv}")
    if jsonl_file:
        jsonl_file.close()
        print(f"wrote {args.jsonl}")

    summarise(cap)

    if cap.errors:
        print(f"\nINVALID: {len(cap.errors)} problem(s)", file=sys.stderr)
        for err in cap.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("\nPASS: capture is complete (sequence 1..N with no gaps, no drops)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
