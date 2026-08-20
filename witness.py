#!/usr/bin/env python3
"""Witness Receipt v0: a small, portable evidence receipt CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"RECORDED", "OBSERVED", "VERIFIED", "BLOCKED", "UNRESOLVED"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_value(value: str) -> Any:
    """Accept a JSON string or a path to a JSON file."""
    candidate = Path(value)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def evidence_items(paths: list[str], base: Path) -> list[dict[str, Any]]:
    items = []
    for index, raw in enumerate(paths, start=1):
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"evidence file not found: {raw}")
        retained_as = Path("evidence") / f"{index:03d}-{path.name}"
        items.append({
            "id": f"evidence-{index}",
            "kind": "file",
            "source": path.name,
            "collected_at": now(),
            "digest": sha256(path),
            "size_bytes": path.stat().st_size,
            "retained_as": str(retained_as),
        })
        out = base / retained_as
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)
    return items


def validate(receipt: dict[str, Any]) -> list[str]:
    errors = []
    if not isinstance(receipt, dict):
        return ["receipt must be a JSON object"]
    for section in ("request", "authority", "action", "evidence", "result"):
        if section not in receipt:
            errors.append(f"missing section: {section}")
        elif not isinstance(receipt[section], dict):
            errors.append(f"{section} must be an object")
    if errors:
        return errors
    status = receipt.get("result", {}).get("status")
    if status not in STATUSES:
        errors.append(f"result.status must be one of {sorted(STATUSES)}")
    if status == "VERIFIED" and not receipt.get("result", {}).get("verification_mechanism"):
        errors.append("VERIFIED receipts require result.verification_mechanism")
    operations = receipt["action"].get("operations", [])
    if not isinstance(operations, list) or not all(isinstance(item, str) for item in operations):
        errors.append("action.operations must be a list of strings")
    items = receipt["evidence"].get("items")
    if not isinstance(items, list):
        errors.append("evidence.items must be a list")
    else:
        seen_paths = set()
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                errors.append(f"evidence.items[{index}] must be an object")
                continue
            retained_as = item.get("retained_as")
            digest = item.get("digest")
            if not isinstance(retained_as, str) or not retained_as:
                errors.append(f"evidence.items[{index}].retained_as must be a non-empty string")
            elif retained_as in seen_paths:
                errors.append(f"duplicate retained evidence path: {retained_as}")
            else:
                seen_paths.add(retained_as)
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                errors.append(f"evidence.items[{index}].digest must be a SHA-256 digest")
    return errors


def markdown(receipt: dict[str, Any]) -> str:
    req, auth, action, result = (receipt[k] for k in ("request", "authority", "action", "result"))
    lines = [
        f"# Witness Receipt `{receipt['receipt_id']}`", "",
        f"**Status:** `{result['status']}`  ",
        f"**Created:** {receipt['created_at']}  ",
        f"**Schema:** {receipt['schema_version']}", "",
        "## Request", f"**Objective:** {req.get('objective', '')}",
        f"**Target / scope:** {req.get('scope', '')}",
        f"**Success criteria:** {req.get('success_criteria', '')}",
        f"**Exclusions:** {req.get('exclusions', '')}",
        f"**Stop conditions:** {req.get('stop_conditions', '')}", "",
        "## Authority", f"**Principal:** {auth.get('principal', '')}",
        f"**Actor:** {auth.get('actor', '')}",
        f"**Capability / boundary:** {auth.get('boundary', '')}", "",
        "## Action",
    ]
    for item in action.get("operations", []):
        lines.append(f"- {item}")
    lines += ["", "## Evidence"]
    for item in receipt["evidence"].get("items", []):
        lines.append(f"- `{item['id']}` — {item['source']} ({item['digest']})")
    lines += ["", "## Result", f"**Claim:** {result.get('claim', '')}"]
    if result.get("verification_mechanism"):
        lines.append(f"**Verification mechanism:** {result['verification_mechanism']}")
    if result.get("unknowns"):
        lines.append(f"**Unknowns:** {result['unknowns']}")
    return "\n".join(lines) + "\n"


def create(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser()
    receipt = {
        "schema_version": "witness-receipt/v0",
        "receipt_id": args.id,
        "created_at": now(),
        "request": {
            "objective": args.objective, "scope": args.scope,
            "success_criteria": args.success, "exclusions": args.exclusions,
            "stop_conditions": args.stop,
        },
        "authority": {
            "principal": args.principal, "actor": args.actor,
            "capability": args.capability, "boundary": args.boundary,
            "evidence": args.authority_evidence,
        },
        "action": {"operations": args.operation, "deviations": args.deviation},
        "evidence": {"items": []},
        "result": {
            "status": args.status, "claim": args.claim,
            "verification_mechanism": args.verify_mechanism,
            "unknowns": args.unknowns,
        },
    }
    errors = validate(receipt)
    if errors:
        raise ValueError("; ".join(errors))
    out.mkdir(parents=True, exist_ok=True)
    receipt["evidence"]["items"] = evidence_items(args.evidence, out)
    errors = validate(receipt)
    if errors:
        raise ValueError("; ".join(errors))
    (out / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "receipt.md").write_text(markdown(receipt), encoding="utf-8")
    print(f"Created {out / 'receipt.json'}")
    print(f"Status: {args.status}")
    return 0


def verify(args: argparse.Namespace) -> int:
    root = Path(args.receipt).resolve()
    if not root.is_dir():
        raise ValueError(f"receipt path is not a directory: {args.receipt}")
    data = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        print("UNRESOLVED")
        for error in errors:
            print(f"- {error}")
        return 1
    checked = 0
    for item in data["evidence"]["items"]:
        retained_as = Path(item["retained_as"])
        retained = (root / retained_as).resolve()
        try:
            retained.relative_to(root)
        except ValueError:
            errors.append(f"retained evidence escapes receipt package: {item['retained_as']}")
            checked += 1
            continue
        if not retained.is_file():
            errors.append(f"missing retained evidence: {item['retained_as']}")
        elif sha256(retained) != item["digest"]:
            errors.append(f"digest mismatch: {item['retained_as']}")
        checked += 1
    if errors:
        print("UNRESOLVED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Receipt package intact: structure valid and {checked} evidence item(s) matched.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="witness", description="Create portable Witness Receipts.")
    sub = p.add_subparsers(required=True)
    c = sub.add_parser("create", help="write receipt.json, receipt.md, and retained evidence")
    c.add_argument("--out", default="receipt")
    c.add_argument("--id", default="receipt-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    c.add_argument("--objective", required=True)
    c.add_argument("--scope", required=True)
    c.add_argument("--success", required=True)
    c.add_argument("--principal", required=True)
    c.add_argument("--actor", required=True)
    c.add_argument("--boundary", required=True)
    c.add_argument("--claim", required=True)
    c.add_argument("--status", choices=sorted(STATUSES), default="RECORDED")
    c.add_argument("--operation", action="append", default=[])
    c.add_argument("--evidence", action="append", default=[])
    c.add_argument("--exclusions", default="")
    c.add_argument("--stop", default="")
    c.add_argument("--capability", default="")
    c.add_argument("--authority-evidence", default="")
    c.add_argument("--deviation", action="append", default=[])
    c.add_argument("--verify-mechanism", default="")
    c.add_argument("--unknowns", default="")
    c.set_defaults(func=create)
    v = sub.add_parser("verify", help="re-hash retained evidence and validate a receipt")
    v.add_argument("receipt")
    v.set_defaults(func=verify)
    return p


if __name__ == "__main__":
    try:
        parsed = parser().parse_args()
        raise SystemExit(parsed.func(parsed))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)