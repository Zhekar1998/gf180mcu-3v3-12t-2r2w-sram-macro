#!/usr/bin/env python3
"""Gate GDS pin-to-route coincidence for row-select and column periphery routes."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "verification" / "results" / "gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate"
AUDIT = ROOT / "scripts" / "audit_gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment.rb"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    audit_json = OUT / "pin_route_alignment_audit.json"
    audit_stderr = OUT / "pin_route_alignment_audit.stderr.log"
    klayout = shutil.which("klayout")
    if klayout is None:
        manifest = {
            "status": "FAIL",
            "counts": {"FAIL": 1},
            "checks": [
                {
                    "scope": "tooling",
                    "check": "klayout available",
                    "status": "FAIL",
                    "detail": "klayout not found",
                    "evidence": rel(audit_json),
                }
            ],
        }
        audit_json.write_text(json.dumps({"error": "klayout not found"}, indent=2) + "\n", encoding="utf-8")
        audit_stderr.write_text("", encoding="utf-8")
    else:
        audit_json.unlink(missing_ok=True)
        cmd = [
            klayout,
            "-b",
            "-r",
            str(AUDIT),
            "-rd",
            f"out={audit_json}",
        ]
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        audit_stderr.write_text(proc.stderr, encoding="utf-8")
        if not audit_json.exists():
            audit_json.write_text(proc.stdout or json.dumps({"error": "empty audit output"}, indent=2) + "\n", encoding="utf-8")

        try:
            audit = json.loads(audit_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            audit = {"status": "FAIL", "results": [], "error": f"unparseable audit JSON: {exc}"}

        checks: list[dict[str, object]] = []
        for item in audit.get("results", []):
            macro = str(item.get("macro"))
            checks.append(
                {
                    "scope": macro,
                    "check": "dummy route fill/poly absent",
                    "status": "PASS" if int(item.get("dummy_route_layer_total", -1)) == 0 else "FAIL",
                    "detail": f"dummy_route_layer_shapes={item.get('dummy_route_layer_shapes')}",
                    "evidence": rel(audit_json),
                }
            )
            checks.append(
                {
                    "scope": macro,
                    "check": "legacy M4 WL stubs absent",
                    "status": "PASS" if int(item.get("legacy_m4_wl_stub_like_shapes", -1)) == 0 else "FAIL",
                    "detail": f"legacy_m4_wl_stub_like_shapes={item.get('legacy_m4_wl_stub_like_shapes')}",
                    "evidence": rel(audit_json),
                }
            )
            row_select = item.get("row_select", {})
            checks.append(
                {
                    "scope": macro,
                    "check": "row-select pins coincide with routed WL/RWL lines",
                    "status": "PASS" if int(row_select.get("missing_points", -1)) == 0 and int(row_select.get("checked_points", 0)) > 0 else "FAIL",
                    "detail": f"checked={row_select.get('checked_points')} missing={row_select.get('missing_points')}",
                    "evidence": rel(audit_json),
                }
            )
            column = item.get("column_periphery", {})
            checks.append(
                {
                    "scope": macro,
                    "check": "column periphery pins coincide with routed lines",
                    "status": "PASS" if int(column.get("missing_points", -1)) == 0 and int(column.get("checked_points", 0)) > 0 else "FAIL",
                    "detail": f"checked={column.get('checked_points')} missing={column.get('missing_points')}",
                    "evidence": rel(audit_json),
                }
            )
        if not checks:
            checks.append(
                {
                    "scope": "audit",
                    "check": "audit produced macro results",
                    "status": "FAIL",
                    "detail": audit.get("error", "no macro results"),
                    "evidence": rel(audit_json),
                }
            )
        if proc.returncode != 0 and audit.get("status") == "PASS":
            checks.append(
                {
                    "scope": "audit",
                    "check": "klayout audit exit code",
                    "status": "FAIL",
                    "detail": f"returncode={proc.returncode}",
                    "evidence": rel(audit_stderr),
                }
            )
        counts = Counter(str(check["status"]) for check in checks)
        manifest = {
            "status": "PASS" if counts.get("FAIL", 0) == 0 and audit.get("status") == "PASS" else "FAIL",
            "counts": dict(sorted(counts.items())),
            "audit": rel(audit_json),
            "stderr": rel(audit_stderr),
            "checks": checks,
        }

    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Pin/Route Alignment Gate",
        "",
        f"- Status: `{manifest['status']}`",
        f"- Counts: `{manifest['counts']}`",
        "",
        "| Scope | Check | Status | Detail | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in manifest["checks"]:
        lines.append(
            f"| `{check['scope']}` | `{check['check']}` | `{check['status']}` | {check['detail']} | `{check['evidence']}` |"
        )
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"GF180MCU 12T SRAM pin/route alignment gate: {manifest['status']} {manifest['counts']}")
    print(rel(OUT / "MANIFEST.json"))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
