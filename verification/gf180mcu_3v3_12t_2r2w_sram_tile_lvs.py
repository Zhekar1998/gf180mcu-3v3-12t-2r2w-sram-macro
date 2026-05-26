#!/usr/bin/env python3
"""Run Netgen LVS on extracted 4x4 tile subcircuits from published reports."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from gf180mcu_3v3_12t_2r2w_sram_lvs_common import (
    TILE_CELL,
    pdk_file_from_env,
    require_path,
    run_netgen_lvs,
    write_reference_cdl,
)


PUBLIC_TILE_CELL = "gf180mcu_3v3_12t_2r2w_sram_4x4_tile"


def default_reports_path() -> Path:
    return Path("reports/local_signoff_full")


@dataclass(frozen=True)
class SpiceSource:
    name: str
    text: str


@dataclass(frozen=True)
class ReportTileLvsResult:
    source: str
    tile_cell: str
    status: str
    layout_devices: int | None
    reference_devices: int | None
    layout_nets: int | None
    reference_nets: int | None
    layout_spice: str
    reference_cdl: str
    netgen_lvs_log: str
    netgen_stdout_log: str

    @property
    def failed(self) -> bool:
        return self.status not in {"match", "match_unique"}


def read_sources(path: Path) -> list[SpiceSource]:
    if path.suffix == ".zip":
        return read_sources_from_zip(path)
    if path.is_file():
        return [SpiceSource(str(path), path.read_text())]
    if path.is_dir():
        return [
            SpiceSource(str(spice), spice.read_text())
            for spice in sorted(path.rglob("*.current_pdk.spice"))
        ]
    raise FileNotFoundError(path)


def read_sources_from_zip(path: Path) -> list[SpiceSource]:
    sources: list[SpiceSource] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("__MACOSX/") or "/._" in name:
                continue
            if not name.endswith(".current_pdk.spice"):
                continue
            if "/local_signoff_full/" not in name:
                continue
            sources.append(
                SpiceSource(
                    name,
                    archive.read(name).decode("utf-8", errors="replace"),
                )
            )
    return sources


def logical_spice_lines(text: str) -> list[str]:
    lines: list[str] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if current is not None:
                current += " " + line[1:].strip()
            continue
        if current is not None:
            lines.append(current)
        current = line
    if current is not None:
        lines.append(current)
    return lines


def find_tile_cell(text: str, preferred: str | None) -> str:
    subckts = []
    for line in logical_spice_lines(text):
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt":
            subckts.append(fields[1])
    if preferred and preferred in subckts:
        return preferred
    for candidate in (PUBLIC_TILE_CELL, TILE_CELL):
        if candidate in subckts:
            return candidate
    matches = [
        cell
        for cell in subckts
        if "12t" in cell
        and "4x4" in cell
        and ("tile" in cell or "routed_5layer_direct" in cell)
    ]
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError(f"could not identify tile subckt; candidates={matches or subckts[:8]}")


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip("/"))
    return cleaned[-180:] if len(cleaned) > 180 else cleaned


def run_one(
    *,
    source: SpiceSource,
    preferred_tile_cell: str | None,
    out_dir: Path,
    netgen_lvs: str,
    netgen_setup: Path,
) -> ReportTileLvsResult:
    tile_cell = find_tile_cell(source.text, preferred_tile_cell)
    target_dir = out_dir / safe_name(source.name)
    layout_dir = target_dir / "layout"
    lvs_dir = target_dir / "lvs"
    layout_dir.mkdir(parents=True, exist_ok=True)
    lvs_dir.mkdir(parents=True, exist_ok=True)

    layout_spice = layout_dir / "layout.current_pdk.spice"
    layout_spice.write_text(source.text)
    reference_cdl = lvs_dir / f"{tile_cell}.independent_reference.cdl"
    write_reference_cdl(
        path=reference_cdl,
        tile_cell=tile_cell,
        rows=4,
        cols=4,
        leaf_cell="gf180mcu_3v3_12t_2r2w_bitcell",
    )

    lvs_log = lvs_dir / f"{tile_cell}.netgen_lvs.log"
    stdout_log = lvs_dir / f"{tile_cell}.netgen_stdout.log"
    status, layout_devices, reference_devices, layout_nets, reference_nets = run_netgen_lvs(
        tile_cell=tile_cell,
        layout_spice=layout_spice,
        reference_cdl=reference_cdl,
        netgen_lvs=netgen_lvs,
        netgen_setup=netgen_setup,
        lvs_log=lvs_log,
        stdout_log=stdout_log,
    )

    return ReportTileLvsResult(
        source=source.name,
        tile_cell=tile_cell,
        status=status,
        layout_devices=layout_devices,
        reference_devices=reference_devices,
        layout_nets=layout_nets,
        reference_nets=reference_nets,
        layout_spice=str(layout_spice),
        reference_cdl=str(reference_cdl),
        netgen_lvs_log=str(lvs_log),
        netgen_stdout_log=str(stdout_log),
    )


def write_manifest(out_dir: Path, results: list[ReportTileLvsResult]) -> None:
    payload = {
        "status": "PASS" if not any(result.failed for result in results) else "FAIL",
        "results": [asdict(result) for result in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "MANIFEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Report Extracted 4x4 Tile LVS",
        "",
        "| Source | Tile cell | Status | Devices | Nets |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for result in results:
        devices = (
            f"{result.layout_devices}/{result.reference_devices}"
            if result.layout_devices is not None and result.reference_devices is not None
            else "unknown"
        )
        nets = (
            f"{result.layout_nets}/{result.reference_nets}"
            if result.layout_nets is not None and result.reference_nets is not None
            else "unknown"
        )
        lines.append(f"| `{result.source}` | `{result.tile_cell}` | `{result.status}` | `{devices}` | `{nets}` |")
    lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=default_reports_path())
    parser.add_argument("--tile-cell", default=None, help="Tile subckt name. Defaults to auto-detect.")
    parser.add_argument("--out-dir", type=Path, default=Path("verification/results/gf180mcu_3v3_12t_2r2w_sram_tile_lvs"))
    parser.add_argument("--netgen-lvs", default="netgen-lvs")
    parser.add_argument("--netgen-setup", type=Path, default=None)
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args(argv)

    netgen_setup = require_path(
        args.netgen_setup or pdk_file_from_env("netgen"),
        description="GF180 Netgen setup",
        option="--netgen-setup",
    )
    sources = read_sources(args.path)
    if not sources:
        raise SystemExit(f"no .current_pdk.spice sources found in {args.path}")

    results: list[ReportTileLvsResult] = []
    had_error = False
    for source in sources:
        try:
            result = run_one(
                source=source,
                preferred_tile_cell=args.tile_cell,
                out_dir=args.out_dir,
                netgen_lvs=args.netgen_lvs,
                netgen_setup=netgen_setup,
            )
        except Exception as exc:
            had_error = True
            print(f"[ERROR] {source.name}: {exc}", file=sys.stderr)
            if not args.keep_going:
                return 2
            continue

        results.append(result)
        status = "PASS" if not result.failed else "FAIL"
        print(
            f"[{status}] {source.name}: LVS={result.status}, "
            f"devices={result.layout_devices}/{result.reference_devices}, "
            f"nets={result.layout_nets}/{result.reference_nets}"
        )
        if result.failed and not args.keep_going:
            break

    write_manifest(args.out_dir, results)
    return 1 if had_error or any(result.failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
