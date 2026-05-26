#!/usr/bin/env python3
"""Run Magic extraction/PEX directly from the published macro GDS wrappers.

This is the release-facing full-GDS extraction gate.  It intentionally reads
the packaged GDS, not stale Magic source cells, so wrapper shorts introduced by
GDS merge/routing are visible to the same flow that emits the PEX netlists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COLUMN_GDS = ROOT / "reports" / "column_periphery_gds_merge" / "MANIFEST.json"
DEFAULT_OUT = ROOT / "reports" / "full_gds_lvs_pex"
SHORT_RE = re.compile(r'Ports "([^"]+)" and "([^"]+)" are electrically shorted')


@dataclass(frozen=True)
class ExtractParams:
    extract_style: str
    blackbox: str
    cthresh: float
    rthresh: float
    extresist: str
    resistor_tee: str
    extresist_threshold: float
    extresist_tolerance: float
    pex_nets: list[str]
    rc_enabled: bool


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_magicrc() -> Path | None:
    env = os.environ.get("GF180_MAGICRC")
    if env and Path(env).is_file():
        return Path(env)
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        for relpath in (
            "gf180mcuD/libs.tech/magic/gf180mcuD.magicrc",
            "libs.tech/magic/gf180mcuD.magicrc",
        ):
            candidate = Path(pdk_root) / relpath
            if candidate.is_file():
                return candidate
    roots = [
        Path.home() / "detronyx_npu" / "third_party" / "pdk" / "volare" / "volare" / "gf180mcu" / "versions",
        Path.home() / ".volare" / "gf180mcu" / "versions",
        Path("/usr/local/share/pdk") / "gf180mcuD" / "libs.tech" / "magic",
    ]
    for root in roots:
        if root.is_file() and root.name == "gf180mcuD.magicrc":
            return root
        if not root.exists():
            continue
        matches = sorted(root.glob("*/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"))
        if matches:
            return matches[-1]
        direct = root / "gf180mcuD.magicrc"
        if direct.is_file():
            return direct
    return None


def tcl_word(value: str | Path) -> str:
    text = str(value)
    return "{" + text.replace("\\", "\\\\").replace("}", "\\}") + "}"


def tcl_list(values: list[str]) -> str:
    return " ".join(tcl_word(value) for value in values)


def write_gds_extract_tcl(path: Path, params: ExtractParams) -> None:
    lines = [
        "proc mark {msg} {",
        "    set fp [open $::env(STEP_LOG) a]",
        "    puts $fp $msg",
        "    close $fp",
        "}",
        "crashbackups stop",
        "drc off",
        "set topcell $::env(MAGIC_TOPCELL)",
        "mark {gds read begin}",
        "gds read $::env(GDS_PATH)",
        "mark {gds read done}",
        "load $topcell",
        "select top cell",
        "expand",
        f"extract style {params.extract_style}",
        "mark {extract unique begin}",
        "extract unique",
        "mark {extract unique done}",
        "extract path $::env(EXT_DIR)",
        "extract no all",
        "mark {extract all begin}",
        "extract all",
        "mark {extract all done}",
        "ext2sim labels on",
        "mark {ext2sim begin}",
        "ext2sim -p $::env(EXT_DIR) $topcell",
        "mark {ext2sim done}",
    ]
    if params.rc_enabled:
        lines.extend(
            [
                f"extresist threshold {params.extresist_threshold}",
                f"extresist tolerance {params.extresist_tolerance}",
                "extresist extout on",
                "extresist silent on",
                "if {[info exists ::env(PEX_NETS)] && $::env(PEX_NETS) ne \"\"} {",
                "    eval extresist include $::env(PEX_NETS)",
                "}",
                "mark {extresist all begin}",
                "extresist all",
                "mark {extresist all done}",
            ]
        )
    lines.extend(
        [
        "ext2spice lvs",
        f"ext2spice blackbox {params.blackbox}",
        "mark {ext2spice lvs begin}",
        "ext2spice -p $::env(EXT_DIR) -o $::env(PEX_LVS_SPICE)",
        "mark {ext2spice lvs done}",
        ]
    )
    if params.rc_enabled:
        lines.extend(
            [
                f"ext2spice cthresh {params.cthresh}",
                f"ext2spice rthresh {params.rthresh}",
                f"ext2spice extresist {params.extresist}",
                f"ext2spice resistor tee {params.resistor_tee}",
                f"ext2spice blackbox {params.blackbox}",
                "mark {ext2spice rc begin}",
                "ext2spice -p $::env(EXT_DIR) -o $::env(PEX_RC_SPICE)",
                "mark {ext2spice rc done}",
            ]
        )
    lines.append("quit -noprompt")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def run_magic_gds_pex(
    *,
    macro: str,
    gds: Path,
    out_dir: Path,
    magic: str,
    magic_rc: Path,
    params: ExtractParams,
    timeout_sec: int,
) -> dict[str, Any]:
    macro_out = out_dir / macro
    macro_out.mkdir(parents=True, exist_ok=True)
    ext_dir = macro_out / "extfiles"
    ext_dir.mkdir(parents=True, exist_ok=True)
    tcl = macro_out / "run_full_gds_extract_pex.tcl"
    log = macro_out / f"{macro}.magic_full_gds_pex.log"
    step_log = macro_out / f"{macro}.magic_full_gds_pex.steps.log"
    lvs_spice = macro_out / f"{macro}.full_gds.current_pdk.spice"
    rc_spice = macro_out / f"{macro}.full_gds.current_pdk_rc.spice"
    write_gds_extract_tcl(tcl, params)

    env = os.environ.copy()
    resolved_magic_rc = magic_rc.resolve()
    if len(resolved_magic_rc.parents) >= 4:
        env["PDK_ROOT"] = str(resolved_magic_rc.parents[3])
    env.update(
        {
            "MAGIC_TOPCELL": macro,
            "GDS_PATH": str(gds.resolve()),
            "EXT_DIR": str(ext_dir.resolve()),
            "PEX_LVS_SPICE": str(lvs_spice.resolve()),
            "PEX_RC_SPICE": str(rc_spice.resolve()),
            "PEX_NETS": tcl_list(params.pex_nets),
            "STEP_LOG": str(step_log.resolve()),
        }
    )
    step_log.write_text("", encoding="utf-8")
    started = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(
            [magic, "-dnull", "-noconsole", "-rcfile", str(magic_rc)],
            cwd=ROOT,
            text=True,
            input=tcl.read_text(encoding="utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=timeout_sec,
            check=False,
        )
        timed_out = False
        output = proc.stdout
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        output += f"\nTIMEOUT after {timeout_sec}s\n"
        returncode = 124
    log.write_text(output, encoding="utf-8")
    shorts = sorted({"/".join(pair) for pair in SHORT_RE.findall(output)})
    lvs_bytes = lvs_spice.stat().st_size if lvs_spice.exists() else 0
    rc_bytes = rc_spice.stat().st_size if rc_spice.exists() else 0
    status = "PASS" if returncode == 0 and not shorts and lvs_bytes > 0 and (not params.rc_enabled or rc_bytes > 0) else "FAIL"
    if timed_out:
        status = "TIMEOUT"
    return {
        "macro": macro,
        "status": status,
        "started_utc": started,
        "returncode": returncode,
        "timed_out": timed_out,
        "gds": rel(gds),
        "magic_rc": str(magic_rc),
        "log": rel(log),
        "step_log": rel(step_log),
        "tcl": rel(tcl),
        "ext_dir": rel(ext_dir),
        "lvs_spice": rel(lvs_spice),
        "rc_spice": rel(rc_spice),
        "lvs_spice_bytes": lvs_bytes,
        "rc_spice_bytes": rc_bytes,
        "electrical_shorts": shorts,
        "lvs_spice_stats": spice_stats(lvs_spice),
        "rc_spice_stats": spice_stats(rc_spice),
    }


def selected_items(manifest: dict[str, Any], macros: list[str]) -> list[dict[str, Any]]:
    items = manifest.get("results", [])
    if not macros or macros == ["all"]:
        return items
    wanted = set(macros)
    by_macro = {item["macro"]: item for item in items}
    missing = sorted(wanted - set(by_macro))
    if missing:
        raise SystemExit(f"unknown macro(s): {', '.join(missing)}")
    return [by_macro[macro] for macro in macros]


def write_readme(out_dir: Path, results: list[dict[str, Any]], params: ExtractParams) -> None:
    lines = [
        "# Full GDS LVS/PEX",
        "",
        "Magic extraction/PEX run directly from the packaged macro GDS wrappers.",
        "",
        f"- `blackbox`: `{params.blackbox}`",
        f"- `cthresh`: `{params.cthresh}`",
        f"- `rthresh`: `{params.rthresh}`",
        f"- `extresist`: `{params.extresist}`",
        f"- `resistor_tee`: `{params.resistor_tee}`",
        f"- `pex_nets`: `{params.pex_nets or ['all']}`",
        "",
        "| Macro | Status | Shorts | LVS bytes | RC bytes | MOS | R | C | Log |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        stats = item.get("rc_spice_stats") or item.get("lvs_spice_stats") or {}
        lines.append(
            f"| `{item['macro']}` | `{item['status']}` | {len(item.get('electrical_shorts', []))} | "
            f"{item.get('lvs_spice_bytes', 0)} | {item.get('rc_spice_bytes', 0)} | "
            f"{stats.get('mos', 0)} | {stats.get('resistors', 0)} | {stats.get('capacitors', 0)} | "
            f"`{item.get('log')}` |"
        )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--column-gds-manifest", type=Path, default=DEFAULT_COLUMN_GDS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--macro", action="append", default=[], help="Macro to extract; use all or omit for all macros.")
    parser.add_argument("--magic", default=shutil.which("magic") or "magic")
    parser.add_argument("--magic-rc", type=Path, default=None)
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--blackbox", choices=("on", "off"), default="off")
    parser.add_argument("--cthresh", type=float, default=0.0)
    parser.add_argument("--rthresh", type=float, default=0.0)
    parser.add_argument("--extresist", choices=("on", "off"), default="on")
    parser.add_argument("--resistor-tee", choices=("on", "off"), default="on")
    parser.add_argument("--extresist-threshold", type=float, default=0.0)
    parser.add_argument("--extresist-tolerance", type=float, default=10.0)
    parser.add_argument("--pex-net", action="append", default=[], help="Restrict extresist to a net; omit for all nets.")
    parser.add_argument("--no-rc", action="store_true")
    args = parser.parse_args()

    magic_rc = args.magic_rc or discover_magicrc()
    if magic_rc is None or not magic_rc.is_file():
        raise SystemExit("missing GF180 Magic rcfile; pass --magic-rc or set GF180_MAGICRC/PDK_ROOT")

    manifest = load_json(args.column_gds_manifest)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    params = ExtractParams(
        extract_style="ngspice()",
        blackbox=args.blackbox,
        cthresh=args.cthresh,
        rthresh=args.rthresh,
        extresist=args.extresist,
        resistor_tee=args.resistor_tee,
        extresist_threshold=args.extresist_threshold,
        extresist_tolerance=args.extresist_tolerance,
        pex_nets=args.pex_net,
        rc_enabled=not args.no_rc,
    )

    results = []
    for item in selected_items(manifest, args.macro or ["all"]):
        macro = item["macro"]
        gds = ROOT / item["gds"]
        results.append(
            run_magic_gds_pex(
                macro=macro,
                gds=gds,
                out_dir=out_dir,
                magic=args.magic,
                magic_rc=magic_rc,
                params=params,
                timeout_sec=args.timeout_sec,
            )
        )

    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    status = "PASS" if counts.get("FAIL", 0) == 0 and counts.get("TIMEOUT", 0) == 0 else "FAIL"
    output = {
        "package": "gf180mcu-3v3-12t-2r2w-sram-macro",
        "status": status,
        "counts": counts,
        "scope": "Magic extraction/PEX from packaged macro GDS wrappers",
        "column_gds_manifest": rel(args.column_gds_manifest),
        "params": asdict(params),
        "results": results,
        "lvs_note": "Device-expanded layout extraction is produced here. Full schematic-vs-layout Netgen comparison requires a separately maintained full macro transistor reference CDL.",
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    write_readme(out_dir, results, params)
    print(f"GF180MCU 12T SRAM full GDS LVS/PEX: {status} {counts}")
    print(rel(out_dir / "MANIFEST.json"))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
