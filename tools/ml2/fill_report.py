#!/usr/bin/env python3
"""Insert the generated tables (report/results2/tables.md) into
report/ML_REPORT.md at every <!-- T:name --> marker. Re-runnable: a filled
block is <!-- T:name --> ... <!-- /T:name --> and is replaced in place."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "report" / "ML_REPORT.md"
TABLES = ROOT / "report" / "results2" / "tables.md"


def main():
    parts = re.split(r"<!-- (\w+) -->\n", TABLES.read_text())
    tables = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    text = REPORT.read_text()
    text = re.sub(r"<!-- T:(\w+) -->\n.*?<!-- /T:\1 -->", r"<!-- T:\1 -->", text, flags=re.S)
    missing = []

    def fill(m):
        name = m.group(1)
        if name not in tables:
            missing.append(name)
            return m.group(0)
        return f"<!-- T:{name} -->\n{tables[name]}\n<!-- /T:{name} -->"

    text = re.sub(r"<!-- T:(\w+) -->", fill, text)
    REPORT.write_text(text)
    print(f"filled {len(re.findall(r'<!-- /T:', text))} tables"
          + (f"; missing: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
