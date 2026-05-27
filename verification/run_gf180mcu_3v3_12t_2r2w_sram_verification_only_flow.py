#!/usr/bin/env python3
"""Run the release verification flow without rebuilding physical collateral.

This orchestrator is deliberately limited to checks that consume already
published GDS, extracted reports, manifests, and packaged verification decks.
It must not run array/periphery builders, placers, routers, GDS rewriters, or
merge scripts.  The output is a single trust-audit report under
``reports/verification_only_flow``.
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports" / "verification_only_flow"

FORBIDDEN_COMMAND_PATTERNS = (
    "build_gf180",
    "build_2r2w",
    "build_physical",
    "merge_gf180",
    "place_gf180",
    "route_gf180",
    "rewrite_gf180",
)

FAIL_PATTERNS = {
    "bad_device_location": re.compile(r"Bad Device Location"),
    "missing_device": re.compile(r"Couldn't find device"),
    "extract_node_error": re.compile(r"Error in extracting node"),
    "electrical_short": re.compile(r"electrically shorted"),
    "traceback": re.compile(r"\bTraceback\b"),
    "same_file_error": re.compile(r"\bSameFileError\b"),
    "json_fail_status": re.compile(r'"status"\s*:\s*"(?:FAIL|TIMEOUT)"'),
    "json_timeout_true": re.compile(r'"timed_out"\s*:\s*true'),
    "markdown_fail_status": re.compile(r"`(?:FAIL|TIMEOUT)`"),
    "netlists_do_not_match": re.compile(r"Netlists do not match"),
    "nonzero_magic_drc": re.compile(r"Total DRC errors found:\s*[1-9][0-9]*"),
}

WARN_PATTERNS = {
    "json_warn_status": re.compile(r'"status"\s*:\s*"WARN"'),
    "markdown_warn_status": re.compile(r"`WARN`"),
    "markdown_open_status": re.compile(r"`OPEN`"),
    "status_warn": re.compile(r"\bStatus:\s*`WARN`"),
}

SCAN_EXTENSIONS = {".json", ".md", ".log", ".csv", ".txt", ".tcl"}
SCAN_IGNORED_DIRS = (
    ROOT / "reports" / "debug",
    ROOT / "verification" / "results" / "spice",
)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: list[str]
    required: bool = True
    timeout_sec: int | None = None


@dataclass
class CommandResult:
    name: str
    argv: list[str]
    required: bool
    status: str
    returncode: int | None
    timed_out: bool
    duration_sec: float
    stdout_log: str
    stderr_log: str


@dataclass
class PatternHit:
    severity: str
    pattern: str
    path: str
    line: int
    text: str


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


def discover_klayout_drc_dir() -> Path | None:
    env = os.environ.get("GF180_KLAYOUT_DRC_DIR")
    if env and (Path(env) / "rule_decks" / "density.drc").is_file():
        return Path(env)
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        for relpath in (
            "gf180mcuD/libs.tech/klayout/drc",
            "libs.tech/klayout/drc",
            "gf180mcu/versions/current/gf180mcuD/libs.tech/klayout/drc",
        ):
            candidate = Path(pdk_root) / relpath
            if (candidate / "rule_decks" / "density.drc").is_file():
                return candidate
    roots = [
        Path.home() / "IHP-Open-PDK",
        Path.home() / ".volare" / "gf180mcu" / "versions",
        Path("/usr/local/share/pdk"),
    ]
    for root in roots:
        if not root.exists():
            continue
        matches = sorted(root.glob("**/gf180mcuD/libs.tech/klayout/drc"))
        for candidate in reversed(matches):
            if (candidate / "rule_decks" / "density.drc").is_file():
                return candidate
        direct = root / "gf180mcuD" / "libs.tech" / "klayout" / "drc"
        if (direct / "rule_decks" / "density.drc").is_file():
            return direct
    return None


def discover_netgen_setup() -> Path | None:
    for name in ("GF180_NETGEN_SETUP", "NETGEN_SETUP"):
        value = os.environ.get(name)
        if value and Path(value).is_file():
            return Path(value)
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        for relpath in (
            "gf180mcuD/libs.tech/netgen/setup.tcl",
            "libs.tech/netgen/setup.tcl",
            "gf180mcu/versions/current/gf180mcuD/libs.tech/netgen/setup.tcl",
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
        matches = sorted(root.glob("**/gf180mcuD/libs.tech/netgen/setup.tcl"))
        if matches:
            return matches[-1]
        direct = root / "gf180mcuD" / "libs.tech" / "netgen" / "setup.tcl"
        if direct.is_file():
            return direct
    return None


def assert_verification_only(commands: list[CommandSpec]) -> None:
    for spec in commands:
        joined = " ".join(spec.argv)
        for pattern in FORBIDDEN_COMMAND_PATTERNS:
            if pattern in joined:
                raise SystemExit(f"refusing non-verification command in flow: {joined}")


def command_log_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def run_command(spec: CommandSpec, out_dir: Path) -> CommandResult:
    log_base = out_dir / "logs" / command_log_name(spec.name)
    log_base.parent.mkdir(parents=True, exist_ok=True)
    stdout_log = log_base.with_suffix(".stdout.log")
    stderr_log = log_base.with_suffix(".stderr.log")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            spec.argv,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=spec.timeout_sec,
            check=False,
        )
        timed_out = False
        returncode: int | None = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr += f"\nTIMEOUT after {spec.timeout_sec}s\n"
    duration = time.monotonic() - started
    stdout_log.write_text(stdout, encoding="utf-8")
    stderr_log.write_text(stderr, encoding="utf-8")
    status = "PASS" if returncode == 0 and not timed_out else "FAIL"
    if timed_out:
        status = "TIMEOUT"
    if not spec.required and status != "PASS":
        status = "WARN"
    return CommandResult(
        name=spec.name,
        argv=spec.argv,
        required=spec.required,
        status=status,
        returncode=returncode,
        timed_out=timed_out,
        duration_sec=round(duration, 3),
        stdout_log=rel(stdout_log),
        stderr_log=rel(stderr_log),
    )


def iter_scan_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*"):
            if any(path.is_relative_to(ignored) for ignored in SCAN_IGNORED_DIRS):
                continue
            if "__pycache__" in path.parts:
                continue
            if path.is_file() and path.suffix in SCAN_EXTENSIONS:
                files.append(path)
    return sorted(set(files))


def scan_patterns(roots: list[Path], max_hits_per_file: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for path in iter_scan_files(roots):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        per_file_hits = 0
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, pattern in FAIL_PATTERNS.items():
                if pattern.search(line):
                    hits.append(PatternHit("FAIL", name, rel(path), line_no, line.strip()[:240]))
                    per_file_hits += 1
                    break
            else:
                for name, pattern in WARN_PATTERNS.items():
                    if pattern.search(line):
                        hits.append(PatternHit("WARN", name, rel(path), line_no, line.strip()[:240]))
                        per_file_hits += 1
                        break
            if per_file_hits >= max_hits_per_file:
                break
    return hits


def status_counts(items: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in items:
        counts[status] = counts.get(status, 0) + 1
    return counts


def extract_manifest_statuses(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        data = load_json(path)
    except Exception as exc:  # noqa: BLE001 - this is an audit report
        return [{"path": rel(path), "status": "FAIL", "detail": f"JSON parse error: {exc}"}]

    def walk(obj: Any, pointer: str) -> None:
        if isinstance(obj, dict):
            if "status" in obj:
                rows.append({"path": rel(path), "status": str(obj.get("status")), "detail": pointer or "/"})
            for key, value in obj.items():
                walk(value, f"{pointer}/{key}")
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                walk(value, f"{pointer}/{idx}")

    walk(data, "")
    return rows


def manifest_audit() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted((ROOT / "reports").glob("**/MANIFEST.json")):
        if any(path.is_relative_to(ignored) for ignored in SCAN_IGNORED_DIRS):
            continue
        rows.extend(extract_manifest_statuses(path))
    for path in sorted((ROOT / "verification" / "results").glob("**/MANIFEST.json")):
        if any(path.is_relative_to(ignored) for ignored in SCAN_IGNORED_DIRS):
            continue
        rows.extend(extract_manifest_statuses(path))
    return rows


def build_commands(args: argparse.Namespace, out_dir: Path) -> list[CommandSpec]:
    python = sys.executable
    timeout = None if args.timeout_sec <= 0 else args.timeout_sec
    netgen_args: list[str] = []
    if args.netgen_setup is not None:
        netgen_args = ["--netgen-setup", str(args.netgen_setup)]

    full_gds_no_rc = out_dir / "full_gds_lvs_pex_no_rc_all"
    full_gds_power = out_dir / "full_gds_lvs_pex_power_rc"
    local_signoff = out_dir / "local_signoff_full"

    commands = [
        CommandSpec("leaf storage ngspice checks", [python, "verification/run_leaf_storage_checks.py"], timeout_sec=timeout),
        CommandSpec("release LVS gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_lvs_gate.py", "--keep-going", *netgen_args], timeout_sec=timeout),
        CommandSpec("tile LVS gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_tile_lvs.py", "--keep-going", *netgen_args], timeout_sec=timeout),
        CommandSpec("macro blackbox LVS gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_macro_lvs.py", "--keep-going", *netgen_args], timeout_sec=timeout),
        CommandSpec("fast connectivity tripwire", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_connectivity_check.py"], timeout_sec=timeout),
        CommandSpec("periphery leaf DRC/LVS evidence gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_periphery_lvs.py"], timeout_sec=timeout),
        CommandSpec("GDS leaf containment audit", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_gds_leaf_containment.py"], timeout_sec=timeout),
        CommandSpec("stdcell control collateral gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_gate.py", "--require-macro-gds-instances"], timeout_sec=timeout),
        CommandSpec("stdcell placement gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_placement_gate.py", "--require-row-select-placement"], timeout_sec=timeout),
        CommandSpec("stdcell GDS containment gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_gds_gate.py"], timeout_sec=timeout),
          CommandSpec("row-select GDS gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_row_select_gds_gate.py"], timeout_sec=timeout),
          CommandSpec("stdcell control routing gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_routing_gate.py"], timeout_sec=timeout),
          CommandSpec("column periphery GDS gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py"], timeout_sec=timeout),
          CommandSpec("pin/route alignment geometry gate", [python, "verification/gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate.py"], timeout_sec=timeout),
          CommandSpec(
              "full-GDS no-RC extraction short audit",
            [
                python,
                "scripts/run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py",
                "--timeout-sec",
                str(args.magic_timeout_sec),
                "--no-rc",
                "--out-dir",
                str(full_gds_no_rc),
                "--magic-rc",
                str(args.magic_rc),
            ],
            timeout_sec=None,
        ),
        CommandSpec(
            "512x8 VDD/VSS RC PEX smoke",
            [
                python,
                "scripts/run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py",
                "--timeout-sec",
                str(args.magic_timeout_sec),
                "--macro",
                "gf180mcu_3v3_12t_2r2w_sram_512x8",
                "--pex-net",
                "VDD",
                "--pex-net",
                "VSS",
                "--out-dir",
                str(full_gds_power),
                "--magic-rc",
                str(args.magic_rc),
            ],
            timeout_sec=None,
        ),
    ]

    if args.include_full_net_rc:
        commands.append(
            CommandSpec(
                "parallel full-GDS all-net RC PEX characterization attempt",
                [
                    python,
                    "verification/run_gf180mcu_3v3_12t_2r2w_sram_parallel_rc_pex.py",
                    "--timeout-sec",
                    str(args.full_net_rc_timeout_sec),
                    "--jobs",
                    str(args.full_net_rc_jobs),
                    "--out-dir",
                    str(out_dir / "full_gds_lvs_pex_all_net_rc"),
                    "--magic-rc",
                    str(args.magic_rc),
                ],
                required=False,
                timeout_sec=None,
            )
        )

    local_args = [
        python,
        "scripts/run_gf180mcu_3v3_12t_2r2w_sram_local_signoff.py",
        "--final-manifest",
        "reports/final_physical/MANIFEST.json",
        "--primitive-manifest",
        "reports/control_leaf_library/MANIFEST.json",
        "--stdcell-control-manifest",
        "reports/stdcell_control_integration/MANIFEST.json",
        "--stdcell-placement-manifest",
        "reports/stdcell_control_placement/MANIFEST.json",
        "--stdcell-gds-manifest",
        "reports/stdcell_control_gds_merge/MANIFEST.json",
        "--row-select-placement-manifest",
        "reports/stdcell_row_select_placement/MANIFEST.json",
        "--row-select-gds-manifest",
        "reports/stdcell_row_select_gds_merge/MANIFEST.json",
        "--stdcell-routing-manifest",
        "reports/stdcell_control_signal_routing/MANIFEST.json",
        "--column-periphery-manifest",
        "reports/column_periphery_gds_merge/MANIFEST.json",
        "--full-gds-extract-manifest",
        str(full_gds_no_rc / "MANIFEST.json"),
        "--full-gds-power-rc-manifest",
        str(full_gds_power / "MANIFEST.json"),
        "--out-dir",
        str(local_signoff),
        "--magic-rc",
        str(args.magic_rc),
        "--gf180-klayout-drc-dir",
        str(args.gf180_klayout_drc_dir),
    ]
    if args.skip_klayout:
        local_args.append("--skip-klayout")
    commands.append(CommandSpec("packaged local signoff rerun", local_args, timeout_sec=None))
    return commands


def write_reports(
    out_dir: Path,
    command_results: list[CommandResult],
    pattern_hits: list[PatternHit],
    manifest_rows: list[dict[str, str]],
    status: str,
) -> None:
    manifest_status_summary = status_counts(row["status"] for row in manifest_rows)
    manifest = {
        "status": status,
        "scope": "verification-only flow; consumes existing generated collateral and published GDS",
        "forbidden_command_patterns": list(FORBIDDEN_COMMAND_PATTERNS),
        "command_counts": status_counts(result.status for result in command_results),
        "pattern_counts": status_counts(hit.severity for hit in pattern_hits),
        "manifest_status_counts": manifest_status_summary,
        "commands": [asdict(result) for result in command_results],
        "pattern_hits": [asdict(hit) for hit in pattern_hits],
        "manifest_statuses": manifest_rows,
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Verification-Only Flow",
        "",
        f"- Overall status: `{status}`",
        "- Scope: existing published GDS, reports, manifests, and packaged verification decks only.",
        "- Rebuild/merge/place/route/rewrite commands are forbidden by this orchestrator.",
        "",
        "## Commands",
        "",
        "| Check | Status | Return | Seconds | Stdout | Stderr |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for result in command_results:
        lines.append(
            f"| `{result.name}` | `{result.status}` | `{result.returncode}` | {result.duration_sec:.3f} | "
            f"`{result.stdout_log}` | `{result.stderr_log}` |"
        )

    lines.extend(
        [
            "",
            "## Pattern Scan",
            "",
            "| Severity | Pattern | File | Line | Text |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    if pattern_hits:
        for hit in pattern_hits[:400]:
            safe_text = hit.text.replace("|", "\\|")
            lines.append(f"| `{hit.severity}` | `{hit.pattern}` | `{hit.path}` | {hit.line} | {safe_text} |")
        if len(pattern_hits) > 400:
            lines.append(f"| `INFO` | `truncated` | `` | 0 | {len(pattern_hits) - 400} additional scan hits in MANIFEST.json |")
    else:
        lines.append("| `PASS` | `none` | `` | 0 | no fail/warn patterns matched |")

    lines.extend(
        [
            "",
            "## Manifest Status Summary",
            "",
            "| Status | Count |",
            "| --- | ---: |",
        ]
    )
    for key, value in sorted(manifest_status_summary.items()):
        lines.append(f"| `{key}` | {value} |")

    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout-sec", type=int, default=0, help="Per-command timeout for short Python gates; 0 disables it.")
    parser.add_argument("--magic-timeout-sec", type=int, default=900)
    parser.add_argument("--include-full-net-rc", action="store_true", help="Also attempt all-net RC PEX from packaged GDS. This can take hours.")
    parser.add_argument("--full-net-rc-timeout-sec", type=int, default=43200)
    parser.add_argument("--full-net-rc-jobs", type=int, default=0, help="Parallel Magic jobs for --include-full-net-rc; 0 means one job per selected macro up to CPU count.")
    parser.add_argument("--magic-rc", type=Path, default=None)
    parser.add_argument("--gf180-klayout-drc-dir", type=Path, default=None)
    parser.add_argument("--netgen-setup", type=Path, default=None)
    parser.add_argument("--skip-klayout", action="store_true")
    parser.add_argument("--max-scan-hits-per-file", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out_dir.exists():
        out_dir = args.out_dir.resolve()
        reports_dir = (ROOT / "reports").resolve()
        if out_dir.parent != reports_dir or out_dir.name != "verification_only_flow":
            raise SystemExit(f"refusing to clean non-standard verification output directory: {args.out_dir}")
        shutil.rmtree(out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.magic_rc is None:
        args.magic_rc = discover_magicrc()
    if args.magic_rc is None or not args.magic_rc.is_file():
        raise SystemExit("missing GF180 Magic rcfile; pass --magic-rc or set GF180_MAGICRC/PDK_ROOT")

    if args.gf180_klayout_drc_dir is None:
        args.gf180_klayout_drc_dir = discover_klayout_drc_dir()
    if args.gf180_klayout_drc_dir is None or not (args.gf180_klayout_drc_dir / "rule_decks" / "density.drc").is_file():
        raise SystemExit("missing GF180 KLayout DRC dir; pass --gf180-klayout-drc-dir")

    if args.netgen_setup is None:
        args.netgen_setup = discover_netgen_setup()

    commands = build_commands(args, args.out_dir)
    assert_verification_only(commands)

    command_results: list[CommandResult] = []
    for spec in commands:
        print(f"[verification-only] {spec.name}")
        result = run_command(spec, args.out_dir)
        command_results.append(result)
        print(f"  -> {result.status} rc={result.returncode} seconds={result.duration_sec:.3f}")

    pattern_hits = scan_patterns(
        [
            ROOT / "reports",
            ROOT / "verification" / "results",
            args.out_dir,
        ],
        max_hits_per_file=args.max_scan_hits_per_file,
    )
    manifest_rows = manifest_audit()

    required_command_fail = any(result.required and result.status not in {"PASS"} for result in command_results)
    scan_fail = any(hit.severity == "FAIL" for hit in pattern_hits)
    manifest_fail = any(row["status"] in {"FAIL", "TIMEOUT"} for row in manifest_rows)
    status = "FAIL" if required_command_fail or scan_fail or manifest_fail else "PASS"
    if status == "PASS" and any(hit.severity == "WARN" for hit in pattern_hits):
        status = "WARN"

    write_reports(args.out_dir, command_results, pattern_hits, manifest_rows, status)
    print(f"GF180MCU 12T SRAM verification-only flow: {status}")
    print(rel(args.out_dir / "MANIFEST.json"))
    return 0 if status in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
