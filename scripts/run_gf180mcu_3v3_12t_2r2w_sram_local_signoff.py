#!/usr/bin/env python3
"""Run the local open-source signoff gate for GF180MCU 12T SRAM macros.

This script intentionally separates tool-backed PASS/FAIL from items that are
only audit proxies in an open-source flow.  It runs/collects:

* Magic DRC evidence from the final physical package;
* Magic hierarchical extraction for top-level pin/LVS evidence;
* staged Netgen LVS evidence for transistor-level control leaves;
* physical Avalon stdcell-control GDS merge and signal-route evidence;
* final macro abstract pin LVS against the extracted top subckt;
* full-GDS hierarchical extraction, power-RC, and short-audit evidence;
* GF180MCU KLayout antenna and density decks;
* ngspice disturb/conflict and VDD sweep evidence as the packaged SNM proxy;
* a conservative local EM/IR power-strap audit.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEASURE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*([-+0-9.eE]+)")
DRC_RE = re.compile(r"(?:Total DRC errors found|DRC error count):\s*(\d+)")
BAD_DEVICE_RE = re.compile(r"Bad Device Location")
MISSING_DEVICE_RE = re.compile(r"Couldn't find device")
EXTRACT_NODE_ERROR_RE = re.compile(r"Error in extracting node")


@dataclass(frozen=True)
class Check:
    area: str
    check: str
    status: str
    evidence: str
    detail: str


def add(checks: list[Check], area: str, check: str, status: str, evidence: Path | str, detail: str) -> None:
    checks.append(Check(area, check, status, str(evidence), detail))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_ok(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def magic_log_issues(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"bad_device_locations": 0, "missing_devices": 0, "extract_node_errors": 0}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "bad_device_locations": len(BAD_DEVICE_RE.findall(text)),
        "missing_devices": len(MISSING_DEVICE_RE.findall(text)),
        "extract_node_errors": len(EXTRACT_NODE_ERROR_RE.findall(text)),
    }


def has_magic_log_issues(issues: dict[str, int]) -> bool:
    return any(int(value) > 0 for value in issues.values())


def stdcell_control_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing stdcell control manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    avalon_files = manifest.get("avalon", {}).get("files", [])
    matrices = manifest.get("control_matrices", [])
    missing = [str(root / str(item.get("path", ""))) for item in avalon_files if not file_ok(root / str(item.get("path", "")))]
    missing += [str(root / str(item.get("cdl", ""))) for item in matrices if not file_ok(root / str(item.get("cdl", "")))]
    missing += [str(root / str(item.get("macro_abstract_cdl", ""))) for item in matrices if not file_ok(root / str(item.get("macro_abstract_cdl", "")))]
    avalon_instances = sum(sum(item.get("stdcell_instances", {}).values()) for item in matrices)
    row_select_instances = sum(sum(item.get("custom_row_select_instances", {}).values()) for item in matrices)
    if missing:
        return "FAIL", f"missing={missing[:5]}, total_missing={len(missing)}"
    if len(matrices) != 4 or avalon_instances <= 0 or row_select_instances <= 0:
        return "FAIL", f"matrices={len(matrices)}, avalon_instances={avalon_instances}, row_select_instances={row_select_instances}"
    return "PASS", f"matrices={len(matrices)}, avalon_instances={avalon_instances}, custom_row_select_instances={row_select_instances}"


def stdcell_placement_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing stdcell placement manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    missing: list[str] = []
    bad: list[str] = []
    placed = 0
    deferred = 0
    max_util = 0.0
    for item in results:
        if item.get("status") != "PASS" or item.get("footprint_unchanged") is not True:
            bad.append(f"{item.get('macro')}: status={item.get('status')} footprint={item.get('footprint_unchanged')}")
        expected = int(item.get("stdcell_instances_expected", -1))
        count = int(item.get("stdcell_instances_placed", -2))
        placed += max(count, 0)
        deferred += int(item.get("deferred_row_select_instances", 0))
        max_util = max(max_util, float(item.get("max_row_utilization", 0.0)))
        if expected != count or count <= 0:
            bad.append(f"{item.get('macro')}: expected={expected} placed={count}")
        for key in ("def", "placement_csv"):
            path = root / str(item.get(key, ""))
            if not file_ok(path):
                missing.append(str(path))
    if len(results) != 4:
        bad.append(f"expected 4 macro placement results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, placed_stdcells={placed}, deferred_row_select={deferred}, max_row_util={max_util:.3f}"


def stdcell_gds_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing stdcell GDS merge manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    missing: list[str] = []
    bad: list[str] = []
    inserted = 0
    for item in results:
        macro = item.get("macro")
        gds = root / str(item.get("gds", ""))
        if not file_ok(gds):
            missing.append(str(gds))
        if item.get("status") != "PASS" or item.get("footprint_unchanged") is not True:
            bad.append(f"{macro}: status={item.get('status')} footprint={item.get('footprint_unchanged')}")
        expected = int(item.get("expected_instances", -1))
        actual = sum(int(v) for v in item.get("direct_avalon_instance_counts", {}).values())
        inserted += max(actual, 0)
        if expected != actual or actual <= 0:
            bad.append(f"{macro}: expected={expected} actual={actual}")
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if len(results) != 4:
        bad.append(f"expected 4 macro GDS merge results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, placed_gds_stdcells={inserted}, footprint_unchanged=True"


def row_select_placement_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing row-select placement manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    bad: list[str] = []
    missing: list[str] = []
    row_selects = 0
    placed = 0
    for item in results:
        macro = item.get("macro")
        if item.get("status") != "PASS" or item.get("footprint_unchanged") is not True:
            bad.append(f"{macro}: status={item.get('status')} footprint={item.get('footprint_unchanged')}")
        rows = int(item.get("row_select_instances", -1))
        cells = int(item.get("placed_stdcells", -2))
        row_selects += max(rows, 0)
        placed += max(cells, 0)
        if cells != rows * 4 or rows <= 0:
            bad.append(f"{macro}: row_selects={rows} placed_stdcells={cells}")
        for key in ("def", "placement_csv", "expanded_cdl", "macro_expanded_cdl"):
            path = root / str(item.get(key, ""))
            if not file_ok(path):
                missing.append(str(path))
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if len(results) != 4:
        bad.append(f"expected 4 row-select placement results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, row_selects={row_selects}, placed_stdcells={placed}, footprint_unchanged=True"


def row_select_gds_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing row-select GDS manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    bad: list[str] = []
    missing: list[str] = []
    inserted = 0
    for item in results:
        macro = item.get("macro")
        gds = root / str(item.get("gds", ""))
        if not file_ok(gds):
            missing.append(str(gds))
        if item.get("status") != "PASS" or item.get("footprint_unchanged") is not True:
            bad.append(f"{macro}: status={item.get('status')} footprint={item.get('footprint_unchanged')}")
        delta = sum(int(v) for v in item.get("expected_delta_counts", {}).values())
        inserted += max(delta, 0)
        final_counts = item.get("direct_avalon_instance_counts", {})
        if delta <= 0 or sum(int(v) for v in final_counts.values()) <= delta:
            bad.append(f"{macro}: delta={delta} final_counts={final_counts}")
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if len(results) != 4:
        bad.append(f"expected 4 row-select GDS merge results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, row_select_gds_stdcells={inserted}, footprint_unchanged=True"


def stdcell_routing_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing stdcell signal routing manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    bad: list[str] = []
    missing: list[str] = []
    nets = 0
    endpoints = 0
    row_select_nets = 0
    macro_pin_nets = 0
    for item in results:
        macro = item.get("macro")
        gds = root / str(item.get("gds", ""))
        csv_path = root / str(item.get("routed_nets_csv", ""))
        if not file_ok(gds):
            missing.append(str(gds))
        if not file_ok(csv_path):
            missing.append(str(csv_path))
        if item.get("status") != "PASS" or item.get("footprint_unchanged") is not True:
            bad.append(f"{macro}: status={item.get('status')} footprint={item.get('footprint_unchanged')}")
        routed_nets = int(item.get("routed_nets", 0))
        routed_endpoints = int(item.get("routed_endpoints", 0))
        rowsel = int(item.get("row_select_input_nets", 0))
        pins = int(item.get("macro_pin_nets", 0))
        nets += routed_nets
        endpoints += routed_endpoints
        row_select_nets += rowsel
        macro_pin_nets += pins
        if routed_nets <= 0 or routed_endpoints <= routed_nets or rowsel <= 0 or pins <= 0:
            bad.append(f"{macro}: routed_nets={routed_nets}, endpoints={routed_endpoints}, row_select_input_nets={rowsel}, macro_pin_nets={pins}")
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if len(results) != 4:
        bad.append(f"expected 4 routed macro results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, routed_nets={nets}, routed_endpoints={endpoints}, row_select_input_nets={row_select_nets}, macro_pin_nets={macro_pin_nets}"


def column_periphery_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing column periphery GDS manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = manifest.get("results", [])
    bad: list[str] = []
    missing: list[str] = []
    instances = 0
    route_shapes = 0
    for item in results:
        macro = item.get("macro")
        gds = root / str(item.get("gds", ""))
        if not file_ok(gds):
            missing.append(str(gds))
        if item.get("status") != "PASS":
            bad.append(f"{macro}: status={item.get('status')}")
        expected = int(item.get("instances_expected", -1))
        counts = item.get("direct_child_counts", {})
        present = sum(
            int(value)
            for key, value in counts.items()
            if key.startswith("detronyx_12t_") and ("write_driver" in key or "precharge_sense" in key)
        )
        shapes = int(item.get("route_shapes", 0))
        bbox = item.get("bbox_after_um", {})
        instances += max(present, 0)
        route_shapes += max(shapes, 0)
        if present != expected or expected <= 0:
            bad.append(f"{macro}: expected_column_leaves={expected} present={present}")
        if shapes <= 0:
            bad.append(f"{macro}: route_shapes={shapes}")
        if float(bbox.get("width_um", 0.0)) <= 0.0 or float(bbox.get("height_um", 0.0)) <= 0.0:
            bad.append(f"{macro}: invalid_bbox={bbox}")
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if len(results) != 4:
        bad.append(f"expected 4 column periphery GDS results, got {len(results)}")
    if missing or bad:
        return "FAIL", f"missing={missing[:3]}, bad={bad[:3]}"
    return "PASS", f"macros={len(results)}, column_leaf_instances={instances}, route_shapes={route_shapes}, expanded_wrapper=True"


def full_gds_extract_summary(root: Path, manifest_path: Path, macro: str) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing full-GDS extraction manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    results = {str(item.get("macro")): item for item in manifest.get("results", [])}
    item = results.get(macro)
    bad: list[str] = []
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if item is None:
        return "FAIL", f"missing macro result in full-GDS extraction manifest: {macro}"
    if item.get("status") != "PASS" or item.get("returncode") != 0 or item.get("timed_out"):
        bad.append(f"status={item.get('status')} returncode={item.get('returncode')} timed_out={item.get('timed_out')}")
    log = root / str(item.get("log", ""))
    issues = magic_log_issues(log)
    if has_magic_log_issues(issues):
        bad.append(f"magic_log_issues={issues}")
    shorts = item.get("electrical_shorts", [])
    if shorts:
        bad.append(f"electrical_shorts={shorts[:4]}")
    lvs_spice = root / str(item.get("lvs_spice", ""))
    if not file_ok(lvs_spice):
        bad.append(f"missing_lvs_spice={lvs_spice}")
        text = ""
    else:
        text = lvs_spice.read_text(encoding="utf-8", errors="replace")
    stats = item.get("lvs_spice_stats", {})
    if int(item.get("lvs_spice_bytes", 0)) <= 0 or int(stats.get("subckt", 0)) <= 0 or int(stats.get("instances", 0)) <= 0:
        bad.append(f"weak_lvs_stats=bytes:{item.get('lvs_spice_bytes')} stats:{stats}")
    required_subckts = (
        macro,
        f"{macro}_array_control_core",
        "detronyx_12t_2w2r_rc4_4x4_routed_5layer_direct",
        "detronyx_12t_precharge_sense_rc1",
        "detronyx_12t_write_driver_rc1",
        "gf180mcu_as_sc_mcu7t3v3__inv_2",
        "gf180mcu_as_sc_mcu7t3v3__nand4_2",
    )
    missing_subckts = [name for name in required_subckts if f".subckt {name}" not in text]
    if missing_subckts:
        bad.append(f"missing_subckts={missing_subckts}")
    if bad:
        return "FAIL", "; ".join(bad[:5])
    return (
        "PASS",
        f"full-GDS extract PASS, shorts=0, subckts={stats.get('subckt')}, instances={stats.get('instances')}, lvs_spice={item.get('lvs_spice')}",
    )


def full_gds_power_rc_summary(root: Path, manifest_path: Path) -> tuple[str, str]:
    if not file_ok(manifest_path):
        return "FAIL", f"missing full-GDS power-RC manifest: {manifest_path}"
    manifest = load_json(manifest_path)
    bad: list[str] = []
    results = manifest.get("results", [])
    if manifest.get("status") != "PASS":
        bad.append(f"manifest_status={manifest.get('status')}")
    if not results:
        bad.append("no_results")
    for item in results:
        rc_spice = root / str(item.get("rc_spice", ""))
        if item.get("status") != "PASS" or item.get("returncode") != 0 or item.get("timed_out"):
            bad.append(f"{item.get('macro')}: status={item.get('status')} returncode={item.get('returncode')} timed_out={item.get('timed_out')}")
        log = root / str(item.get("log", ""))
        issues = magic_log_issues(log)
        if has_magic_log_issues(issues):
            bad.append(f"{item.get('macro')}: magic_log_issues={issues}")
        if item.get("electrical_shorts"):
            bad.append(f"{item.get('macro')}: shorts={item.get('electrical_shorts')[:4]}")
        if int(item.get("rc_spice_bytes", 0)) <= 0 or not file_ok(rc_spice):
            bad.append(f"{item.get('macro')}: missing_rc_spice={rc_spice} bytes={item.get('rc_spice_bytes')}")
    if bad:
        return "FAIL", "; ".join(bad[:5])
    macros = [str(item.get("macro")) for item in results]
    return "PASS", f"macros={macros}, shorts=0, rc_spice_bytes={[item.get('rc_spice_bytes') for item in results]}"


def parse_magic_drc(path: Path) -> int | None:
    if not path.exists():
        return None
    matches = DRC_RE.findall(path.read_text(encoding="utf-8", errors="replace"))
    return int(matches[-1]) if matches else None


def write_extract_tcl(path: Path, *, enable_extresist: bool) -> None:
    lines = [
        "crashbackups stop",
        "drc off",
        "set topcell $::env(MAGIC_TOPCELL)",
        "load $topcell",
        "select top cell",
        "expand",
        "extract style ngspice()",
        "extract unique",
        "extract path $::env(EXT_DIR)",
        "extract no all",
        "extract all",
        "ext2sim labels on",
        "ext2sim -p $::env(EXT_DIR) $topcell",
    ]
    if enable_extresist:
        lines.extend(
            [
                "extresist threshold 0",
                "extresist tolerance 10",
                "extresist extout on",
                "extresist silent on",
                "if {[info exists ::env(PEX_NETS)] && $::env(PEX_NETS) ne \"\"} {",
                "    eval extresist include $::env(PEX_NETS)",
                "}",
                "extresist all",
            ]
        )
    lines.extend(
        [
            "ext2spice lvs",
            "ext2spice blackbox on",
            "ext2spice -p $::env(EXT_DIR) -o $::env(PEX_LVS_SPICE)",
        ]
    )
    if enable_extresist:
        lines.extend(
            [
                "ext2spice cthresh 0",
                "ext2spice rthresh 0",
                "ext2spice extresist on",
                "ext2spice resistor tee on",
                "ext2spice blackbox on",
                "ext2spice -p $::env(EXT_DIR) -o $::env(PEX_RC_SPICE)",
            ]
        )
    lines.append("quit -noprompt")
    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def tcl_list(items: list[str]) -> str:
    escaped = []
    for item in items:
        escaped.append("{" + item.replace("\\", "\\\\").replace("}", "\\}") + "}")
    return " ".join(escaped)


def run_magic_pex(
    *,
    macro: str,
    magic_dir: Path,
    out_dir: Path,
    magic: str,
    magic_rc: Path,
    pex_nets: list[str],
    enable_extresist: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ext_dir = out_dir / "extfiles"
    ext_dir.mkdir(parents=True, exist_ok=True)
    tcl = out_dir / ("run_extract_pex.tcl" if enable_extresist else "run_extract_lvs.tcl")
    log = out_dir / f"{macro}.magic_pex.log"
    lvs_spice = out_dir / f"{macro}.current_pdk.spice"
    rc_spice = out_dir / f"{macro}.current_pdk_rc.spice"
    if not enable_extresist:
        for stale in (out_dir / "run_extract_pex.tcl", rc_spice, ext_dir / f"{macro}.res.ext"):
            if stale.exists():
                stale.unlink()
    write_extract_tcl(tcl, enable_extresist=enable_extresist)
    env = os.environ.copy()
    resolved_magic_rc = magic_rc.resolve()
    if len(resolved_magic_rc.parents) >= 4:
        # gf180mcuD.magicrc expects PDK_ROOT to point at the concrete
        # gf180mcu/versions/<hash> directory, not at the volare root.
        env["PDK_ROOT"] = str(resolved_magic_rc.parents[3])
    env.update(
        {
            "MAGIC_TOPCELL": macro,
            "EXT_DIR": str(ext_dir.resolve()),
            "PEX_LVS_SPICE": str(lvs_spice.resolve()),
            "PEX_RC_SPICE": str(rc_spice.resolve()),
            "PEX_NETS": tcl_list([net for net in ("VDD", "VSS") if net in pex_nets] or pex_nets),
        }
    )
    proc = subprocess.run(
        [magic, "-dnull", "-noconsole", "-rcfile", str(magic_rc)],
        cwd=magic_dir,
        text=True,
        input=tcl.read_text(encoding="utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    log.write_text(proc.stdout, encoding="utf-8")
    return {
        "returncode": proc.returncode,
        "enable_extresist": enable_extresist,
        "log": str(log),
        "lvs_spice": str(lvs_spice),
        "rc_spice": str(rc_spice),
        "lvs_spice_bytes": lvs_spice.stat().st_size if lvs_spice.exists() else 0,
        "rc_spice_bytes": rc_spice.stat().st_size if rc_spice.exists() else 0,
        "lvs_spice_stats": spice_stats(lvs_spice),
        "spice_stats": spice_stats(rc_spice),
        "magic_log_issues": magic_log_issues(log),
    }


def spice_stats(path: Path) -> dict[str, int]:
    stats = {"subckt": 0, "resistors": 0, "capacitors": 0, "mos": 0, "instances": 0}
    if not path.exists():
        return stats
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("+"):
            continue
        low = line.lower()
        if low.startswith(".subckt"):
            stats["subckt"] += 1
        elif line[0] in {"R", "r"}:
            stats["resistors"] += 1
        elif line[0] in {"C", "c"}:
            stats["capacitors"] += 1
        elif line[0] in {"M", "m"}:
            stats["mos"] += 1
        elif line[0] in {"X", "x"}:
            stats["instances"] += 1
    return stats


def subckt_pins(path: Path, cell: str) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines):
        if not line.startswith(f".subckt {cell} "):
            continue
        parts = [line]
        cursor = idx + 1
        while cursor < len(lines) and lines[cursor].startswith("+"):
            parts.append(lines[cursor][1:])
            cursor += 1
        return " ".join(parts).split()[2:]
    return []


def parse_lyrdb_items(path: Path) -> tuple[int | None, list[str]]:
    if not path.exists():
        return None, []
    root = ET.parse(path).getroot()
    items = None
    for child in root:
        if child.tag == "items":
            items = child
            break
    if items is None:
        return None, []
    categories: list[str] = []
    for item in list(items):
        for sub in list(item):
            if sub.tag == "category":
                categories.append(sub.text or "")
                break
    return len(list(items)), sorted(set(categories))[:12]


def run_klayout_deck(
    *,
    klayout: str,
    deck: Path,
    gds: Path,
    topcell: str,
    report: Path,
    log: Path,
    deck_kind: str,
) -> dict[str, Any]:
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()
    if log.exists():
        log.unlink()
    cmd = [
        klayout,
        "-b",
        "-r",
        str(deck),
        "-rd",
        f"input={gds.resolve()}",
        "-rd",
        f"topcell={topcell}",
        "-rd",
        f"report={report.resolve()}",
        "-rd",
        "run_mode=flat",
        "-rd",
        "metal_top=9K",
        "-rd",
        "metal_level=5LM",
        "-rd",
        "thr=1",
    ]
    if deck_kind == "antenna":
        cmd.extend(["-rd", "mim_option=B"])
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log.write_text(proc.stdout, encoding="utf-8")
    items, categories = parse_lyrdb_items(report)
    return {
        "returncode": proc.returncode,
        "report": str(report),
        "log": str(log),
        "violations": items,
        "categories": categories,
    }


def primitive_lvs_summary(path: Path) -> tuple[int, int, list[str]]:
    fails: list[str] = []
    total = 0
    for item in load_json(path):
        total += 1
        lvs = str(item.get("lvs_result", ""))
        pins = int(item.get("disconnected_pins", -1))
        if lvs not in {"match", "match_unique"} or pins != 0:
            fails.append(f"{item.get('primitive')}: lvs={lvs} disconnected={pins}")
    return total, len(fails), fails


def parse_measures(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = MEASURE_RE.match(line)
        if not match:
            continue
        key, raw = match.groups()
        try:
            values[key.lower()] = float(raw)
        except ValueError:
            pass
    return values


def check_vdd_sweep(root: Path) -> tuple[bool, str]:
    spice_dir = root / "verification" / "results" / "spice"
    vdds = ("1p62", "1p80", "2p50", "3p00", "3p30", "3p60")
    cases = [("typical", vtag, spice_dir / f"write_read_retention_typical_{vtag}v.log") for vtag in vdds]
    cases += [
        ("ff", "3p30", spice_dir / "write_read_retention_ff_3p30v.log"),
        ("ss", "3p30", spice_dir / "write_read_retention_ss_3p30v.log"),
    ]
    missing: list[str] = []
    bad: list[str] = []
    for _corner, vtag, path in cases:
        vals = parse_measures(path)
        if not vals:
            missing.append(path.name)
            continue
        if "q_after_write1" not in vals or "qb_after_write0" not in vals:
            bad.append(f"{path.name}: missing write measures")
            continue
        vdd = float(vtag.replace("p", "."))
        if vals["q_after_write1"] < 0.75 * vdd or vals["qb_after_write0"] < 0.75 * vdd:
            bad.append(f"{path.name}: weak rail write q1={vals['q_after_write1']:.3g} qb0={vals['qb_after_write0']:.3g}")
    ok = not missing and not bad
    return ok, f"missing={missing[:4]} bad={bad[:4]} checked={len(cases)} packaged_logs={spice_dir}"


def check_disturb(root: Path) -> tuple[bool, str]:
    spice_dir = root / "verification" / "results" / "spice"
    missing: list[str] = []
    bad: list[str] = []

    def check_file(path: Path, highs: tuple[str, ...], lows: tuple[str, ...]) -> None:
        vals = parse_measures(path)
        if not vals:
            missing.append(path.name)
            return
        for high_key in highs:
            if vals.get(high_key, 0.0) < 2.4:
                bad.append(f"{path.name}:{high_key}={vals.get(high_key)}")
        for low_key in lows:
            if vals.get(low_key, 9.9) > 0.15:
                bad.append(f"{path.name}:{low_key}={vals.get(low_key)}")

    checked = 0
    for corner in ("typical", "ff", "ss"):
        check_file(
            spice_dir / f"dual_read_disturb_{corner}_3p30v.log",
            ("q_after_dual_read",),
            ("qb_after_dual_read",),
        )
        checked += 1
        check_file(
            spice_dir / f"disabled_write_hold_{corner}_3p30v.log",
            ("q_after_disabled_write",),
            ("qb_after_disabled_write",),
        )
        checked += 1
        check_file(
            spice_dir / f"same_data_dual_write_{corner}_3p30v.log",
            ("q_after_dual_write1", "qb_after_dual_write0"),
            ("qb_after_dual_write1", "q_after_dual_write0"),
        )
        checked += 1
    check_file(
        spice_dir / "same_cell_conflict_observation_typical_3p30v.log",
        ("qb_after_conflict",),
        ("q_after_conflict",),
    )
    checked += 1
    ok = not missing and not bad
    return ok, f"missing={missing} bad={bad[:6]} checked={checked} packaged_logs={spice_dir}"


def emir_proxy(item: dict[str, Any]) -> tuple[str, str]:
    width = float(item["width_um"])
    bottom = float(item["control_bottom_um"])
    top = float(item["control_top_um"])
    cols = int(item["tile_grid_cols"])
    rows = int(item["tile_grid_rows"])
    # M5 power rails are full macro width; M4 ties repeat per tile column.
    vss_area = width * bottom
    vdd_area = width * top
    if bottom >= 20.0 and top >= 20.0 and cols >= 16 and rows >= 16:
        return "WARN", f"proxy pass: M5 VSS={bottom:.1f}um, VDD={top:.1f}um over {width:.1f}um; {cols} column ties. No solver-grade current map."
    return "FAIL", f"weak proxy rails: M5 VSS={bottom:.1f}um, VDD={top:.1f}um, cols={cols}, rail_area={vdd_area + vss_area:.1f}um2"


def write_outputs(out_dir: Path, checks: list[Check], tool_runs: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    overall = "FAIL" if counts.get("FAIL", 0) else ("WARN" if counts.get("WARN", 0) or counts.get("OPEN", 0) else "PASS")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "status_counts": counts,
        "tool_runs": tool_runs,
        "checks": [asdict(check) for check in checks],
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# GF180MCU 12T SRAM Local Open-Source Signoff",
        "",
        f"- Overall status: `{overall}`",
        f"- Status counts: `{counts}`",
        "",
        "This is the strongest local open-source gate currently available in this tree.",
        "It is not a foundry signoff replacement.",
        "",
        "| Area | Check | Status | Detail | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        detail = check.detail.replace("|", "/")
        lines.append(f"| `{check.area}` | `{check.check}` | `{check.status}` | {detail} | `{check.evidence}` |")
    lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    csv_lines = ["area,check,status,evidence,detail"]
    for check in checks:
        csv_lines.append(
            ",".join(
                json.dumps(field, ensure_ascii=False)
                for field in (check.area, check.check, check.status, check.evidence, check.detail)
            )
        )
    (out_dir / "summary.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument(
        "--legacy-staged-manifest",
        type=Path,
        default=None,
        help="Optional legacy staged-signoff manifest. Current release packages are self-contained without it.",
    )
    parser.add_argument("--primitive-manifest", type=Path, required=True)
    parser.add_argument("--stdcell-control-manifest", type=Path, default=Path("reports/stdcell_control_integration/MANIFEST.json"))
    parser.add_argument("--stdcell-placement-manifest", type=Path, default=Path("reports/stdcell_control_placement/MANIFEST.json"))
    parser.add_argument("--stdcell-gds-manifest", type=Path, default=Path("reports/stdcell_control_gds_merge/MANIFEST.json"))
    parser.add_argument("--row-select-placement-manifest", type=Path, default=Path("reports/stdcell_row_select_placement/MANIFEST.json"))
    parser.add_argument("--row-select-gds-manifest", type=Path, default=Path("reports/stdcell_row_select_gds_merge/MANIFEST.json"))
    parser.add_argument("--stdcell-routing-manifest", type=Path, default=Path("reports/stdcell_control_signal_routing/MANIFEST.json"))
    parser.add_argument("--column-periphery-manifest", type=Path, default=Path("reports/column_periphery_gds_merge/MANIFEST.json"))
    parser.add_argument("--full-gds-extract-manifest", type=Path, default=Path("reports/full_gds_lvs_pex_no_rc_all/MANIFEST.json"))
    parser.add_argument("--full-gds-power-rc-manifest", type=Path, default=Path("reports/full_gds_lvs_pex_power_rc/MANIFEST.json"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--magic", default="magic")
    parser.add_argument("--magic-rc", type=Path, required=True)
    parser.add_argument("--klayout", default="klayout")
    parser.add_argument("--gf180-klayout-drc-dir", type=Path, required=True)
    parser.add_argument("--macro-filter", action="append", default=[], help="Limit the run to matching macro name(s); useful for pin-LVS/PEX iteration.")
    parser.add_argument("--skip-klayout", action="store_true", help="Skip KLayout density/antenna decks; useful for focused pin-LVS/PEX iteration.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    out_dir = args.out_dir
    final_macros = load_json(args.final_manifest)
    if args.macro_filter:
        allowed = set(args.macro_filter)
        final_macros = [item for item in final_macros if str(item["macro"]) in allowed]
        if not final_macros:
            raise SystemExit(f"no final macros matched --macro-filter={sorted(allowed)}")
    checks: list[Check] = []
    tool_runs: dict[str, Any] = {
        "magic_pex": {},
        "klayout_density": {},
        "klayout_antenna": {},
    }

    if args.legacy_staged_manifest is not None:
        staged_manifest = load_json(args.legacy_staged_manifest)
        add(
            checks,
            "Legacy staged signoff",
            "Prior staged signoff manifest",
            "PASS" if staged_manifest.get("overall_status") in {"PASS", "WARN"} else "FAIL",
            args.legacy_staged_manifest,
            "legacy staged manifest loaded for comparison only; current local gate supersedes it",
        )

    total_prims, primitive_fails, primitive_details = primitive_lvs_summary(args.primitive_manifest)
    add(
        checks,
        "LVS",
        "Custom transistor control primitive Netgen LVS",
        "PASS" if primitive_fails == 0 else "FAIL",
        args.primitive_manifest,
        f"checked={total_prims}, fails={primitive_fails}, details={primitive_details[:3]}",
    )

    stdcell_status, stdcell_detail = stdcell_control_summary(root, args.stdcell_control_manifest)
    add(
        checks,
        "Control",
        "Avalon stdcell control integration",
        stdcell_status,
        args.stdcell_control_manifest,
        stdcell_detail,
    )

    placement_status, placement_detail = stdcell_placement_summary(root, args.stdcell_placement_manifest)
    add(
        checks,
        "Control",
        "Avalon stdcell control placement",
        placement_status,
        args.stdcell_placement_manifest,
        placement_detail,
    )

    gds_status, gds_detail = stdcell_gds_summary(root, args.stdcell_gds_manifest)
    add(
        checks,
        "Control",
        "Avalon stdcell control GDS merge",
        gds_status,
        args.stdcell_gds_manifest,
        gds_detail,
    )

    row_select_place_status, row_select_place_detail = row_select_placement_summary(root, args.row_select_placement_manifest)
    add(
        checks,
        "Control",
        "Avalon row-select/WL-buffer stdcell placement",
        row_select_place_status,
        args.row_select_placement_manifest,
        row_select_place_detail,
    )

    row_select_gds_status, row_select_gds_detail = row_select_gds_summary(root, args.row_select_gds_manifest)
    add(
        checks,
        "Control",
        "Avalon row-select/WL-buffer GDS merge",
        row_select_gds_status,
        args.row_select_gds_manifest,
        row_select_gds_detail,
    )

    routing_status, routing_detail = stdcell_routing_summary(root, args.stdcell_routing_manifest)
    add(
        checks,
        "Control",
        "Avalon stdcell control/predecode signal routing",
        routing_status,
        args.stdcell_routing_manifest,
        routing_detail,
    )

    column_status, column_detail = column_periphery_summary(root, args.column_periphery_manifest)
    add(
        checks,
        "Periphery",
        "Column precharge/sense/write-driver GDS integration",
        column_status,
        args.column_periphery_manifest,
        column_detail,
    )

    density_deck = args.gf180_klayout_drc_dir / "rule_decks" / "density.drc"
    antenna_deck = args.gf180_klayout_drc_dir / "rule_decks" / "antenna.drc"
    for item in final_macros:
        macro = str(item["macro"])
        macro_out = out_dir / macro
        gds = root / str(item["gds"])
        magic_file = root / str(item["magic"])
        spice = root / str(item["spice"])
        drc_log = root / str(item["drc_log"])
        drc_raw = item.get("drc_errors")
        parsed_drc = parse_magic_drc(drc_log)
        if drc_raw is None:
            add(checks, macro, "Magic final macro DRC", "OPEN", drc_log, "top-level Magic DRC skipped in final physical rebuild; staged leaf/tile Magic DRC and KLayout decks remain checked")
        else:
            drc = int(drc_raw)
            add(checks, macro, "Magic final macro DRC", "PASS" if drc == 0 and parsed_drc == 0 else "FAIL", drc_log, f"manifest_drc={drc}, parsed_drc={parsed_drc}")

        ref_pins = subckt_pins(spice, macro)
        pex = run_magic_pex(
            macro=macro,
            magic_dir=magic_file.parent,
            out_dir=macro_out / "pex",
            magic=args.magic,
            magic_rc=args.magic_rc,
            pex_nets=ref_pins,
            enable_extresist=False,
        )
        tool_runs["magic_pex"][macro] = pex
        pex_ok = (
            pex["returncode"] == 0
            and pex["lvs_spice_bytes"] > 0
            and pex["lvs_spice_stats"]["subckt"] > 0
            and not has_magic_log_issues(pex["magic_log_issues"])
        )
        pex_status = "PASS" if pex_ok else "FAIL"
        add(
            checks,
            macro,
            "Magic hierarchical LVS extraction",
            pex_status,
            pex["log"],
            (
                f"lvs_spice_bytes={pex['lvs_spice_bytes']}, stats={pex['lvs_spice_stats']}, "
                f"extresist=False, magic_log_issues={pex['magic_log_issues']}"
            ),
        )

        ext_pins = subckt_pins(Path(pex["lvs_spice"]), macro)
        pin_ok = bool(ref_pins) and set(ref_pins) == set(ext_pins)
        add(checks, macro, "Final abstract pin LVS", "PASS" if pin_ok else "FAIL", pex["lvs_spice"], f"ref_pins={len(ref_pins)}, extracted_pins={len(ext_pins)}, missing={sorted(set(ref_pins) - set(ext_pins))[:6]}, extra={sorted(set(ext_pins) - set(ref_pins))[:6]}")
        full_gds_status, full_gds_detail = full_gds_extract_summary(root, args.full_gds_extract_manifest, macro)
        add(checks, macro, "Full-GDS hierarchical extraction/short audit", full_gds_status, args.full_gds_extract_manifest, full_gds_detail)

        if args.skip_klayout:
            add(checks, macro, "KLayout GF180 density deck", "OPEN", gds, "skipped by --skip-klayout for focused pin-LVS/PEX iteration")
            add(checks, macro, "KLayout GF180 antenna deck", "OPEN", gds, "skipped by --skip-klayout for focused pin-LVS/PEX iteration")
        else:
            density = run_klayout_deck(
                klayout=args.klayout,
                deck=density_deck,
                gds=gds,
                topcell=macro,
                report=macro_out / "density" / f"{macro}.density.lyrdb",
                log=macro_out / "density" / f"{macro}.density.log",
                deck_kind="density",
            )
            tool_runs["klayout_density"][macro] = density
            add(checks, macro, "KLayout GF180 density deck", "PASS" if density["returncode"] == 0 and density["violations"] == 0 else "FAIL", density["report"], f"returncode={density['returncode']}, violations={density['violations']}, sample_categories={density['categories']}")

            antenna = run_klayout_deck(
                klayout=args.klayout,
                deck=antenna_deck,
                gds=gds,
                topcell=macro,
                report=macro_out / "antenna" / f"{macro}.antenna.lyrdb",
                log=macro_out / "antenna" / f"{macro}.antenna.log",
                deck_kind="antenna",
            )
            tool_runs["klayout_antenna"][macro] = antenna
            add(checks, macro, "KLayout GF180 antenna deck", "PASS" if antenna["returncode"] == 0 and antenna["violations"] == 0 else "FAIL", antenna["report"], f"returncode={antenna['returncode']}, violations={antenna['violations']}, sample_categories={antenna['categories']}")

        status, detail = emir_proxy(item)
        add(checks, macro, "Local EM/IR power strap audit", status, root / str(item["pins_json"]), detail)

    vdd_ok, vdd_detail = check_vdd_sweep(root)
    add(checks, "SNM proxy", "12T VDD sweep ngspice", "PASS" if vdd_ok else "FAIL", root / "verification" / "results" / "spice", vdd_detail)
    disturb_ok, disturb_detail = check_disturb(root)
    add(checks, "SNM proxy", "12T disturb/conflict ngspice", "PASS" if disturb_ok else "FAIL", root / "verification" / "results" / "spice", disturb_detail)
    snm_proxy_ok = vdd_ok and disturb_ok
    add(checks, "SNM proxy", "Packaged SNM/read-disturb proxy coverage", "PASS" if snm_proxy_ok else "FAIL", root / "verification" / "results" / "spice", "local proxy closed by VDD sweep plus disturb/conflict logs; final extracted-RC butterfly SNM remains characterization scope, not a local package blocker")
    power_rc_status, power_rc_detail = full_gds_power_rc_summary(root, args.full_gds_power_rc_manifest)
    add(checks, "PEX", "512x8 full-GDS VDD/VSS RC smoke", power_rc_status, args.full_gds_power_rc_manifest, power_rc_detail)

    write_outputs(out_dir, checks, tool_runs)
    counts: dict[str, int] = {}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    print(f"GF180MCU 12T SRAM local open-source signoff: {counts}")
    print(out_dir / "README.md")
    return 1 if counts.get("FAIL", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
