"""Write three authored, reproducible retrieval cases for prefill.py.

These are synthetic documents with predeclared answers, not natural agent-task
acceptance or a general recall benchmark. Full prompts fit the tested 32K route.
"""

import argparse
import hashlib
import json
from pathlib import Path


def cases():
    definitions = (
        ("operations_retry", "At 2026-10-15T12:00Z, may delivery d-42 retry? Reply exactly ALLOW or DENY.", "DENY", (
            "delivery d-42 assigned policy P7 (superseded at 2026-10-15T10:00Z)",
            "delivery d-42 assigned policy P8 (current since 2026-10-15T10:00Z)",
            "policy P7 retry_after 2026-10-15T11:00Z; policy P8 retry_after 2026-10-15T13:00Z",
        )),
        ("appointment_offset", "Does appointment APPT-42 begin at 15:30Z or 16:30Z? Reply exactly 15:30Z or 16:30Z.", "15:30Z", (
            "appointment APPT-42 belongs to corridor C7",
            "corridor C7 has UTC offset -06:00 on 2026-10-15",
            "appointment APPT-42 starts at local 2026-10-15T09:30 in its corridor timezone",
        )),
        ("invoice_rounding", "Which current rounding rule governs invoice INV-42? Reply exactly HALF_EVEN or HALF_UP.", "HALF_EVEN", (
            "invoice INV-42 assigned policy P9 (current)",
            "policy P8 rounding HALF_UP; P8 was superseded",
            "policy P9 rounding HALF_EVEN; effective for assigned invoices",
        )),
    )
    for name, question, expected, facts in definitions:
        lines = []
        for index in range(360):
            digest = hashlib.blake2b(f"{name}:{index}".encode(), digest_size=8).hexdigest()
            lines.append(f"batch {index:04d} record {digest} service audit worker {index % 9} result ok duration_ms {index % 37} event accepted")
        for index, fact in zip((90, 180, 270), facts):
            lines[index] = fact
        yield {"name": name, "document": "\n".join(lines), "question": question, "expected": expected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(case) + "\n" for case in cases()), encoding="utf-8")
    print(f"Wrote three authored cases to {args.output}")
