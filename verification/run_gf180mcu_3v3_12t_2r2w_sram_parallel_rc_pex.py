#!/usr/bin/env python3
"""Run full-net RC PEX from packaged GDS wrappers in parallel.

This is a verification-only RC driver.  It does not rebuild layout collateral;
it fans out independent Magic PEX jobs across the published macro GDS wrappers
and aggregates the per-macro manifests into one report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COLUMN_GDS = ROOT / "reports" / "column_periphery_gds_merge" / "MANIFEST.json"
DEFAULT_OUT = ROOT / "reports" / "parallel_full_net_rc_pex"

FAIL_PATTERNS = {
    "bad_device_location": re.compile(r"Bad Device Location"),
    "missing_device": re.compile(r"Couldn't find device"),
    "extract_node_error": re.compile(r"Error in extracting node"),
    "electrical_short": re.compile(r"electrically shorted"),
    "traceback": re.compile(r"\bTraceback\b"),
    "timeout": re.compile(r"\bTIMEOUT\b"),
}


@dataclass
class MacroRun:
    macro: str
    status: str
    returncode: int | None
    duration_sec: float
    out_dir: str
    stdout_log: str
    stderr_log: str
    manifest: str | None
    rc_spice: str | None
    rc_spice_bytes: int
    rc_spice_stats: dict[str, int]
    pattern_hits: list[dict[str, Any]]


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
            "gf180mcu/versions/current/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc",
        ):
            candidate = Path(pdk_root) / relpath
            if candidate.is_file():
                return candidate
    roots = [
        Path.home() / "IHP-Open-PDK",
        Path.home() / ".volare" / "gf180mcu" / "versions",
        Path("/usr/local/share/pdk"),
    ]
    for root in roots:
        if not root.exists():
            continue
        matches = sorted(root.glob("**/gf180mcuD/libs.tech/magic/gf180mcuD.magicrc"))
        if matches:
            return matches[-1]
        direct = root / "gf180mcuD" / "libs.tech" / "magic" / "gf180mcuD.magicrc"
        if direct.is_file():
            return direct
    return None


def selected_macros(manifest: dict[str, Any], macros: list[str]) -> list[str]:
    names = [item["macro"] for item in manifest.get("results", [])]
    if not macros or macros == ["all"]:
        return names
    wanted = set(macros)
    missing = sorted(wanted - set(names))
    if missing:
        raise SystemExit(f"unknown macro(s): {', '.join(missing)}")
    return [name for name in names if name in wanted]


def scan_file(path: Path, max_hits: int = 50) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not path.is_file():
        return hits
    text = path.read_text(encoding="utf-8", errors="replace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in FAIL_PATTERNS.items():
            if pattern.search(line):
                hits.append({"pattern": name, "path": rel(path), "line": line_no, "text": line.strip()[:240]})
                break
        if len(hits) >= max_hits:
            break
    return hits


def gpu_note() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    note = {
        "nvidia_smi": nvidia_smi,
        "gpu_acceleration": "not_used",
        "reason": "Magic/KLayout/ngspice RC extraction in this flow is CPU-bound and has no CUDA/OpenCL backend.",
    }
    if not nvidia_smi:
        return note
    try:
        proc = subprocess.run([nvidia_smi, "-L"], text=True, capture_output=True, timeout=10, check=False)
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        note["gpu_probe_error"] = str(exc)
        return note
    note["gpu_probe_returncode"] = proc.returncode
    note["gpu_devices"] = [line for line in proc.stdout.splitlines() if line.strip()]
    return note


def run_one_macro(args: argparse.Namespace, macro: str, magic_rc: Path) -> MacroRun:
    out_dir = args.out_dir / "macro_runs" / macro
    log_dir = args.out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / f"{macro}.stdout.log"
    stderr_log = log_dir / f"{macro}.stderr.log"
    argv = [
        sys.executable,
        "scripts/run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py",
        "--column-gds-manifest",
        str(args.column_gds_manifest),
        "--out-dir",
        str(out_dir),
        "--macro",
        macro,
        "--magic",
        args.magic,
        "--magic-rc",
        str(magic_rc),
        "--timeout-sec",
        str(args.timeout_sec),
        "--cthresh",
        str(args.cthresh),
        "--rthresh",
        str(args.rthresh),
        "--extresist-threshold",
        str(args.extresist_threshold),
        "--extresist-tolerance",
        str(args.extresist_tolerance),
        "--blackbox",
        args.blackbox,
        "--extresist",
        args.extresist,
        "--resistor-tee",
        args.resistor_tee,
    ]
    for net in args.pex_net:
        argv.extend(["--pex-net", net])

    started = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    duration = time.monotonic() - started
    stdout_log.write_text(proc.stdout, encoding="utf-8")
    stderr_log.write_text(proc.stderr, encoding="utf-8")

    manifest_path = out_dir / "MANIFEST.json"
    manifest: dict[str, Any] | None = None
    rc_spice: str | None = None
    rc_spice_bytes = 0
    rc_spice_stats: dict[str, int] = {}
    child_status = "FAIL"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        child_status = str(manifest.get("status", "FAIL"))
        results = manifest.get("results") or []
        if results:
            result = results[0]
            rc_spice = result.get("rc_spice")
            rc_spice_bytes = int(result.get("rc_spice_bytes") or 0)
            rc_spice_stats = dict(result.get("rc_spice_stats") or {})

    pattern_hits = scan_file(stdout_log) + scan_file(stderr_log)
    if manifest is not None:
        for result in manifest.get("results", []):
            log = result.get("log")
            if log:
                pattern_hits.extend(scan_file(ROOT / log))

    status = "PASS" if proc.returncode == 0 and child_status == "PASS" and not pattern_hits else "FAIL"
    return MacroRun(
        macro=macro,
        status=status,
        returncode=proc.returncode,
        duration_sec=round(duration, 3),
        out_dir=rel(out_dir),
        stdout_log=rel(stdout_log),
        stderr_log=rel(stderr_log),
        manifest=rel(manifest_path) if manifest_path.is_file() else None,
        rc_spice=rc_spice,
        rc_spice_bytes=rc_spice_bytes,
        rc_spice_stats=rc_spice_stats,
        pattern_hits=pattern_hits,
    )


def write_readme(out_dir: Path, runs: list[MacroRun], status: str, jobs: int, note: dict[str, Any]) -> None:
    lines = [
        "# Parallel Full-Net RC PEX",
        "",
        f"- Overall status: `{status}`",
        "- Scope: full-net Magic RC PEX from packaged macro GDS wrappers only.",
        "- Layout builders, placers, routers, and GDS merge scripts are not invoked.",
        f"- Jobs: `{jobs}`",
        f"- GPU acceleration: `{note['gpu_acceleration']}`; {note['reason']}",
        "",
        "| Macro | Status | Seconds | RC bytes | R | C | MOS | Manifest |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for run in runs:
        stats = run.rc_spice_stats
        lines.append(
            f"| `{run.macro}` | `{run.status}` | {run.duration_sec:.3f} | {run.rc_spice_bytes} | "
            f"{stats.get('resistors', 0)} | {stats.get('capacitors', 0)} | {stats.get('mos', 0)} | "
            f"`{run.manifest or ''}` |"
        )
    lines.extend(["", "## Pattern Hits", "", "| Macro | Pattern | File | Line | Text |", "| --- | --- | --- | ---: | --- |"])
    any_hits = False
    for run in runs:
        for hit in run.pattern_hits[:50]:
            any_hits = True
            safe_text = str(hit["text"]).replace("|", "\\|")
            lines.append(f"| `{run.macro}` | `{hit['pattern']}` | `{hit['path']}` | {hit['line']} | {safe_text} |")
    if not any_hits:
        lines.append("| `all` | `none` | `` | 0 | no RC extraction fail patterns matched |")
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--column-gds-manifest", type=Path, default=DEFAULT_COLUMN_GDS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--macro", action="append", default=[], help="Macro to extract; omit or pass all for every packaged macro.")
    parser.add_argument("--jobs", type=int, default=0, help="Parallel Magic jobs. 0 means min(CPU count, selected macros).")
    parser.add_argument("--magic", default=shutil.which("magic") or "magic")
    parser.add_argument("--magic-rc", type=Path, default=None)
    parser.add_argument("--timeout-sec", type=int, default=43200, help="Per-macro Magic timeout.")
    parser.add_argument("--blackbox", choices=("on", "off"), default="off")
    parser.add_argument("--cthresh", type=float, default=0.0)
    parser.add_argument("--rthresh", type=float, default=0.0)
    parser.add_argument("--extresist", choices=("on", "off"), default="on")
    parser.add_argument("--resistor-tee", choices=("on", "off"), default="on")
    parser.add_argument("--extresist-threshold", type=float, default=0.0)
    parser.add_argument("--extresist-tolerance", type=float, default=10.0)
    parser.add_argument("--pex-net", action="append", default=[], help="Restrict RC extraction to a net. Omit for full-net RC.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    magic_rc = args.magic_rc or discover_magicrc()
    if magic_rc is None or not magic_rc.is_file():
        raise SystemExit("missing GF180 Magic rcfile; pass --magic-rc or set GF180_MAGICRC/PDK_ROOT")

    if args.out_dir.exists():
        out_dir = args.out_dir.resolve()
        reports_dir = (ROOT / "reports").resolve()
        if out_dir.parent != reports_dir or out_dir.name not in {"parallel_full_net_rc_pex", "verification_only_flow"}:
            raise SystemExit(f"refusing to clean non-standard RC output directory: {args.out_dir}")
        shutil.rmtree(out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_json(args.column_gds_manifest)
    macros = selected_macros(manifest, args.macro or ["all"])
    jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 1, len(macros))
    jobs = max(1, min(jobs, len(macros)))
    note = gpu_note()

    print(f"[parallel-rc] macros={len(macros)} jobs={jobs} timeout_sec={args.timeout_sec}")
    print(f"[parallel-rc] gpu_acceleration=not_used reason={note['reason']}")

    runs: list[MacroRun] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_one_macro, args, macro, magic_rc): macro for macro in macros}
        for future in as_completed(futures):
            run = future.result()
            runs.append(run)
            print(f"[parallel-rc] {run.macro}: {run.status} seconds={run.duration_sec:.3f}")
    runs.sort(key=lambda item: item.macro)

    counts: dict[str, int] = {}
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
    status = "PASS" if counts.get("FAIL", 0) == 0 else "FAIL"

    output = {
        "package": "gf180mcu-3v3-12t-2r2w-sram-macro",
        "status": status,
        "counts": counts,
        "scope": "parallel full-net Magic RC PEX from packaged macro GDS wrappers",
        "jobs": jobs,
        "cpu_count": os.cpu_count(),
        "gpu": note,
        "column_gds_manifest": rel(args.column_gds_manifest),
        "pex_nets": args.pex_net or ["all"],
        "runs": [asdict(run) for run in runs],
    }
    (args.out_dir / "MANIFEST.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_readme(args.out_dir, runs, status, jobs, note)
    print(f"GF180MCU 12T SRAM parallel full-net RC PEX: {status} {counts}")
    print(rel(args.out_dir / "MANIFEST.json"))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
