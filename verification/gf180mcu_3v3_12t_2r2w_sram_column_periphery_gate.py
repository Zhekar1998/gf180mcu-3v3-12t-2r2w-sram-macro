#!/usr/bin/env python3
"""Gate for column periphery placement/GDS integration collateral."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "verification" / "results" / "gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate"
PLACEMENT = ROOT / "reports" / "column_periphery_integration" / "MANIFEST.json"
GDS = ROOT / "reports" / "column_periphery_gds_merge" / "MANIFEST.json"
M5_POWER_AUDIT = ROOT / "scripts" / "audit_gf180mcu_3v3_12t_2r2w_sram_m5_power_shorts.rb"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path):
    return json.loads(path.read_text())


def add(results: list[dict[str, str]], macro: str, check: str, status: str, detail: str, evidence: Path) -> None:
    results.append(
        {
            "macro": macro,
            "check": check,
            "status": status,
            "detail": detail,
            "evidence": rel(evidence),
        }
    )


def run_m5_power_audit(macro: str, gds_path: Path) -> tuple[str, str, Path]:
    audit_json = OUT / f"{macro}.m5_power_short_audit.json"
    audit_log = OUT / f"{macro}.m5_power_short_audit.stderr.log"
    klayout = shutil.which("klayout")
    if klayout is None:
        audit_json.write_text(json.dumps({"error": "klayout not found"}, indent=2) + "\n")
        return "FAIL", "klayout not found", audit_json

    cmd = [
        klayout,
        "-b",
        "-r",
        str(M5_POWER_AUDIT),
        "-rd",
        f"gds={gds_path}",
        "-rd",
        f"topcell={macro}",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    audit_json.write_text(proc.stdout if proc.stdout.strip() else json.dumps({"error": "empty audit output"}, indent=2) + "\n")
    audit_log.write_text(proc.stderr)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return "FAIL", f"unparseable audit JSON: {exc}", audit_json
    short_count = int(data.get("short_count", -1))
    status = "PASS" if proc.returncode == 0 and short_count == 0 else "FAIL"
    return status, f"short_count={short_count} m5_regions={data.get('m5_regions')} labels={data.get('m5_power_labels')}", audit_json


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, str]] = []
    if not PLACEMENT.is_file():
        add(results, "column_periphery", "placement manifest exists", "FAIL", "missing", PLACEMENT)
    if not GDS.is_file():
        add(results, "column_periphery", "GDS manifest exists", "FAIL", "missing", GDS)

    if PLACEMENT.is_file():
        placement = load(PLACEMENT)
        add(results, "column_periphery", "placement manifest status", placement.get("status", "FAIL"), f"status={placement.get('status')}", PLACEMENT)
        for item in placement.get("results", []):
            macro = item["macro"]
            expected = int(item["instances"].get("write_driver", 0)) + int(item["instances"].get("precharge_sense", 0))
            expected_ok = expected == 4 * int(macro.split("_")[-1].split("x")[-1])
            add(results, macro, "column leaf instance count", "PASS" if expected_ok else "FAIL", f"instances={item['instances']} expected_total={4 * int(macro.split('_')[-1].split('x')[-1])}", PLACEMENT)
            height_ok = float(item["new_height_um"]) > float(item["old_height_um"])
            add(results, macro, "expanded wrapper height", "PASS" if height_ok else "FAIL", f"old={item['old_height_um']} new={item['new_height_um']}", PLACEMENT)
            phase_ok = int(item["read_phase_rows"]) >= 1 and int(item["write_phase_rows"]) >= 1
            add(results, macro, "phase row assignment", "PASS" if phase_ok else "FAIL", f"read={item['read_phase_rows']} write={item['write_phase_rows']}", PLACEMENT)

    if GDS.is_file():
        gds = load(GDS)
        add(results, "column_periphery", "GDS manifest status", gds.get("status", "FAIL"), f"status={gds.get('status')}", GDS)
        smoke = gds.get("smoke_main_drc")
        if smoke:
            smoke_ok = smoke.get("status") == "PASS" and int(smoke.get("violations", -1)) == 0
            add(results, "column_periphery", "512x8 GF180 main.drc smoke", "PASS" if smoke_ok else "FAIL", f"violations={smoke.get('violations')} report={smoke.get('report')}", GDS)
        for item in gds.get("results", []):
            macro = item["macro"]
            status = item["status"]
            add(results, macro, "GDS wrapper merge", status, f"bbox={item['bbox_after_um']}", GDS)
            counts = item.get("direct_child_counts", {})
            leaf_count = sum(value for key, value in counts.items() if key.startswith("detronyx_12t_") and ("write_driver" in key or "precharge_sense" in key))
            add(results, macro, "leaf cells present in top", "PASS" if leaf_count == item["instances_expected"] else "FAIL", f"leaf_count={leaf_count} expected={item['instances_expected']}", GDS)
            add(results, macro, "route cell present", "PASS" if item.get("route_shapes", 0) > 0 else "FAIL", f"route_cell={item.get('route_cell')} shapes={item.get('route_shapes')}", GDS)
            density_fill_shapes = int(item.get("density_fill_shapes", -1))
            add(results, macro, "route cell dummy fill disabled", "PASS" if density_fill_shapes == 0 else "FAIL", f"density_fill_shapes={density_fill_shapes}", GDS)
            audit_status, audit_detail, audit_evidence = run_m5_power_audit(macro, ROOT / item["gds"])
            add(results, macro, "M5 VDD/VSS short audit", audit_status, audit_detail, audit_evidence)

    counts = Counter(row["status"] for row in results)
    manifest = {
        "status": "PASS" if counts.get("FAIL", 0) == 0 else "FAIL",
        "counts": dict(counts),
        "results": results,
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    lines = [
        "# Column Periphery Gate",
        "",
        "| Macro | Check | Status | Detail | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in results:
        lines.append(f"| `{row['macro']}` | `{row['check']}` | `{row['status']}` | {row['detail']} | `{row['evidence']}` |")
    (OUT / "README.md").write_text("\n".join(lines) + "\n")
    print(f"GF180MCU 12T SRAM column periphery gate: {manifest['status']} {dict(counts)}")
    print(rel(OUT / "MANIFEST.json"))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
