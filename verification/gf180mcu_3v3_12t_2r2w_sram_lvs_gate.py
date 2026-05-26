#!/usr/bin/env python3
"""Gate GF180MCU 3.3V 12T 2R2W SRAM extracted reports with real Netgen LVS checks.

This is intentionally a two-stage LVS gate:

* device LVS for the extracted 4x4 tile subcircuit against an independent
  generated 12T MOS reference;
* macro-top blackbox LVS that treats the checked tile as a leaf and verifies
  that every tile instance signal port remains connected to its expected
  instance-local net rather than to VDD/VSS or another accidental short.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


SUPPLY_PORTS = {"VDD", "VSS", "VSUBS"}
ROW_PINS = ("W0_WL", "W1_WL", "R0_RWL", "R1_RWL")
COL_PINS = ("W0_BL", "W0_BR", "W1_BL", "W1_BR", "R0_RBL", "R1_RBL")

LEAF_DEVICE_TEMPLATE = [
    ("XP_Q", "q", "qb", "VDD", "NWELL", "pfet_03v3", "w=0.28u l=0.28u"),
    ("XN_Q", "q", "qb", "VSS", "VSUBS", "nfet_03v3", "w=0.45u l=0.28u"),
    ("XP_QB", "qb", "q", "VDD", "NWELL", "pfet_03v3", "w=0.28u l=0.28u"),
    ("XN_QB", "qb", "q", "VSS", "VSUBS", "nfet_03v3", "w=0.45u l=0.28u"),
    ("XW0_Q", "q", "W0_WL", "W0_BL", "VSUBS", "nfet_03v3", "w=0.28u l=0.36u"),
    ("XW0_QB", "qb", "W0_WL", "W0_BR", "VSUBS", "nfet_03v3", "w=0.28u l=0.36u"),
    ("XW1_Q", "q", "W1_WL", "W1_BL", "VSUBS", "nfet_03v3", "w=0.28u l=0.36u"),
    ("XW1_QB", "qb", "W1_WL", "W1_BR", "VSUBS", "nfet_03v3", "w=0.28u l=0.36u"),
    ("XR0_Q", "r0_mid", "q", "VSS", "VSUBS", "nfet_03v3", "w=0.53u l=0.28u"),
    ("XR0_SEL", "r0_mid", "R0_RWL", "R0_RBL", "VSUBS", "nfet_03v3", "w=0.53u l=0.28u"),
    ("XR1_Q", "r1_mid", "q", "VSS", "VSUBS", "nfet_03v3", "w=0.53u l=0.28u"),
    ("XR1_SEL", "r1_mid", "R1_RWL", "R1_RBL", "VSUBS", "nfet_03v3", "w=0.53u l=0.28u"),
]


def pdk_file_from_env(kind: str) -> Path | None:
    env_names = {
        "netgen": ("GF180_NETGEN_SETUP", "NETGEN_SETUP"),
    }[kind]
    for name in env_names:
        value = os.environ.get(name)
        if value and Path(value).is_file():
            return Path(value)

    roots: list[Path] = []
    gf180_root = os.environ.get("GF180_PDK_ROOT")
    if gf180_root:
        roots.append(Path(gf180_root))

    pdk_root = os.environ.get("PDK_ROOT")
    pdk_version = os.environ.get("PDK_VERSION")
    if pdk_root and pdk_version:
        roots.append(Path(pdk_root) / "gf180mcu" / "versions" / pdk_version / "gf180mcuD")
        roots.append(Path(pdk_root) / pdk_version / "gf180mcuD")
    if pdk_root:
        roots.append(Path(pdk_root) / "gf180mcuD")

    for root in roots:
        candidate = root / "libs.tech/netgen/setup.tcl"
        if candidate.is_file():
            return candidate
    return None


def require_path(path: Path | None, *, description: str, option: str) -> Path:
    if path is not None and path.is_file():
        return path
    raise SystemExit(f"missing {description}; pass {option} or set the matching GF180 env var")


@dataclass(frozen=True)
class Source:
    name: str
    path: Path
    text: str


@dataclass(frozen=True)
class LvsRow:
    source: str
    scope: str
    macro_cell: str | None
    tile_cell: str
    status: str
    layout_devices: int | None
    reference_devices: int | None
    layout_nets: int | None
    reference_nets: int | None
    tile_instances: int | None
    supply_tied_signal_ports: dict[str, int]
    netgen_lvs_log: str
    netgen_stdout_log: str

    @property
    def passed(self) -> bool:
        return self.status in {"match", "match_unique"} and not self.supply_tied_signal_ports


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


def read_sources(path: Path) -> list[Source]:
    if path.suffix == ".zip":
        return read_sources_from_zip(path)
    if path.is_file():
        return [Source(str(path), path, path.read_text(encoding="utf-8", errors="replace"))]
    if not path.is_dir():
        raise FileNotFoundError(path)
    sources = []
    for spice in sorted(path.rglob("*.current_pdk.spice")):
        sources.append(Source(str(spice), spice, spice.read_text(encoding="utf-8", errors="replace")))
    return sources


def read_sources_from_zip(path: Path) -> list[Source]:
    sources: list[Source] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("__MACOSX/") or "/._" in name:
                continue
            if not name.endswith(".current_pdk.spice"):
                continue
            if "/local_signoff_full/" not in name:
                continue
            sources.append(Source(name, Path(name), archive.read(name).decode("utf-8", errors="replace")))
    return sources


def default_reports_path() -> Path:
    return Path("reports/local_signoff_full")


def subckt_headers(text: str) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for line in logical_spice_lines(text):
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt":
            headers[fields[1]] = fields[2:]
    return headers


def looks_like_tile_cell(cell: str) -> bool:
    lowered = cell.lower()
    return "4x4" in lowered and ("tile" in lowered or "routed_5layer_direct" in lowered)


def identify_cells(source: Source, preferred_macro: str | None, preferred_tile: str | None) -> tuple[str, str, list[str], list[str]]:
    headers = subckt_headers(source.text)
    if preferred_tile is not None:
        tile_cell = preferred_tile
    else:
        matches = [cell for cell in headers if looks_like_tile_cell(cell)]
        if len(matches) != 1:
            raise RuntimeError(f"{source.name}: cannot identify tile subckt from {matches}")
        tile_cell = matches[0]
    if tile_cell not in headers:
        raise RuntimeError(f"{source.name}: missing tile subckt {tile_cell}")

    if preferred_macro is not None:
        macro_cell = preferred_macro
    else:
        matches = [cell for cell in headers if cell != tile_cell]
        if len(matches) != 1:
            raise RuntimeError(f"{source.name}: cannot identify macro subckt from {matches}")
        macro_cell = matches[0]
    if macro_cell not in headers:
        raise RuntimeError(f"{source.name}: missing macro subckt {macro_cell}")
    return macro_cell, tile_cell, headers[macro_cell], headers[tile_cell]


def extract_subckt_block(text: str, cell: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        fields = line.strip().split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt" and fields[1] == cell:
            start = idx
            break
    if start is None:
        raise RuntimeError(f"missing .subckt {cell}")
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip().lower().startswith(".ends"):
            return lines[start : idx + 1]
    raise RuntimeError(f"unterminated .subckt {cell}")


def body_logical_lines(block: list[str]) -> list[str]:
    return logical_spice_lines("\n".join(block[1:-1]))


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip("/"))
    return cleaned[-180:] if len(cleaned) > 180 else cleaned


def format_line(tokens: list[str]) -> list[str]:
    lines: list[str] = []
    current = tokens[0]
    for token in tokens[1:]:
        candidate = f"{current} {token}"
        if len(candidate) > 118:
            lines.append(current)
            current = f"+ {token}"
        else:
            current = candidate
    lines.append(current)
    return lines


def tile_reference_pins(rows: int, cols: int) -> list[str]:
    pins: list[str] = []
    for col in range(cols):
        pins.extend(f"c{col}_{pin.lower()}" for pin in COL_PINS)
    for row in range(rows):
        pins.extend(f"r{row}_{pin.lower()}" for pin in ROW_PINS)
    pins.extend(["VDD", "VSS"])
    return pins


def write_tile_reference(path: Path, *, tile_cell: str, rows: int = 4, cols: int = 4) -> None:
    lines = [
        f"* Independent 12T 2R2W {rows}x{cols} tile reference for {tile_cell}",
        "* Generated from intended MOS topology, not extracted layout.",
        "",
        f".subckt {tile_cell} {' '.join(tile_reference_pins(rows, cols))}",
    ]
    for row in range(rows):
        for col in range(cols):
            nets = {
                "W0_BL": f"c{col}_w0_bl",
                "W0_BR": f"c{col}_w0_br",
                "W1_BL": f"c{col}_w1_bl",
                "W1_BR": f"c{col}_w1_br",
                "R0_RBL": f"c{col}_r0_rbl",
                "R1_RBL": f"c{col}_r1_rbl",
                "W0_WL": f"r{row}_w0_wl",
                "W1_WL": f"r{row}_w1_wl",
                "R0_RWL": f"r{row}_r0_rwl",
                "R1_RWL": f"r{row}_r1_rwl",
                "VDD": "VDD",
                "VSS": "VSS",
            }
            prefix = f"r{row}c{col}"

            def resolve(node: str) -> str:
                if node in nets:
                    return nets[node]
                if node == "VSUBS":
                    return "VSUBS"
                return f"gf180mcu_3v3_12t_2r2w_bitcell{prefix}/{node}"

            for name, drain, gate, source, body, model, params in LEAF_DEVICE_TEMPLATE:
                lines.append(
                    " ".join(
                        [
                            f"X{prefix}_{name}",
                            resolve(drain),
                            resolve(gate),
                            resolve(source),
                            resolve(body),
                            model,
                            params,
                        ]
                    )
                )
    lines.append(f".ends {tile_cell}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_empty_subckt(lines: list[str], *, cell: str, pins: list[str]) -> None:
    lines.extend(format_line([".subckt", cell, *pins]))
    lines.append(f".ends {cell}")


def tile_instance_lines(macro_block: list[str], tile_cell: str) -> list[list[str]]:
    instances = []
    for line in body_logical_lines(macro_block):
        fields = line.split()
        if fields and fields[0].startswith("X") and fields[-1] == tile_cell:
            instances.append(fields)
    if not instances:
        raise RuntimeError(f"no instances of {tile_cell}")
    return instances


def expected_net(instance: str, port: str) -> str:
    if port in SUPPLY_PORTS:
        return port
    return f"{instance[1:]}/{port}"


def write_macro_blackbox_pair(
    *,
    source: Source,
    layout_path: Path,
    reference_path: Path,
    macro_cell: str,
    macro_pins: list[str],
    tile_cell: str,
    tile_pins: list[str],
) -> tuple[int, dict[str, int]]:
    instances = tile_instance_lines(extract_subckt_block(source.text, macro_cell), tile_cell)

    layout_lines = [f"* Layout macro-top blackbox extracted from {source.name}", ""]
    reference_lines = [f"* Independent macro-top blackbox reference for {source.name}", ""]
    for lines in (layout_lines, reference_lines):
        write_empty_subckt(lines, cell=tile_cell, pins=tile_pins)
        lines.append("")
        lines.extend(format_line([".subckt", macro_cell, *macro_pins]))

    tied: dict[str, int] = {}
    for fields in instances:
        instance = fields[0]
        nets = fields[1:-1]
        if len(nets) != len(tile_pins):
            raise RuntimeError(f"{instance}: expected {len(tile_pins)} nets, got {len(nets)}")
        layout_lines.extend(format_line(fields))
        reference_nets = []
        for port, net in zip(tile_pins, nets, strict=True):
            if port not in SUPPLY_PORTS and net in {"VDD", "VSS"}:
                key = f"{port}->{net}"
                tied[key] = tied.get(key, 0) + 1
            reference_nets.append(expected_net(instance, port))
        reference_lines.extend(format_line([instance, *reference_nets, tile_cell]))

    layout_lines.append(f".ends {macro_cell}")
    reference_lines.append(f".ends {macro_cell}")
    layout_path.write_text("\n".join(layout_lines) + "\n", encoding="utf-8")
    reference_path.write_text("\n".join(reference_lines) + "\n", encoding="utf-8")
    return len(instances), tied


def parse_lvs(log: Path, stdout_log: Path) -> tuple[str, int | None, int | None, int | None, int | None]:
    text = ""
    if log.exists():
        text += log.read_text(encoding="utf-8", errors="replace")
    if stdout_log.exists():
        text += "\n" + stdout_log.read_text(encoding="utf-8", errors="replace")
    if "Netlists do not match" in text or "Mismatch" in text:
        status = "mismatch"
    elif "Result: Circuits match uniquely" in text or "Netlists match uniquely" in text:
        status = "match_unique"
    elif "Circuits match correctly" in text or "Subcircuits match" in text:
        status = "match"
    else:
        status = "unknown"
    devices = re.findall(r"Circuit 1 contains\s+(\d+)\s+devices,\s+Circuit 2 contains\s+(\d+)\s+devices", text)
    nets = re.findall(r"Circuit 1 contains\s+(\d+)\s+nets,\s+Circuit 2 contains\s+(\d+)\s+nets", text)
    return (
        status,
        int(devices[-1][0]) if devices else None,
        int(devices[-1][1]) if devices else None,
        int(nets[-1][0]) if nets else None,
        int(nets[-1][1]) if nets else None,
    )


def run_netgen(
    *,
    cell: str,
    layout_spice: Path,
    reference_cdl: Path,
    netgen_lvs: str,
    netgen_setup: Path,
    log: Path,
    stdout: Path,
) -> tuple[str, int | None, int | None, int | None, int | None]:
    proc = subprocess.run(
        [
            netgen_lvs,
            "-batch",
            "lvs",
            f"{layout_spice} {cell}",
            f"{reference_cdl} {cell}",
            str(netgen_setup),
            str(log),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    stdout.write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"netgen failed for {cell}; see {stdout}")
    return parse_lvs(log, stdout)


def check_source(
    *,
    source: Source,
    out_dir: Path,
    netgen_lvs: str,
    netgen_setup: Path,
    preferred_macro: str | None,
    preferred_tile: str | None,
) -> tuple[LvsRow, LvsRow]:
    macro_cell, tile_cell, macro_pins, tile_pins = identify_cells(source, preferred_macro, preferred_tile)
    target = out_dir / safe_name(source.name)
    layout_dir = target / "layout"
    lvs_dir = target / "lvs"
    layout_dir.mkdir(parents=True, exist_ok=True)
    lvs_dir.mkdir(parents=True, exist_ok=True)

    layout_spice = layout_dir / "layout.current_pdk.spice"
    layout_spice.write_text(source.text, encoding="utf-8")
    tile_ref = lvs_dir / f"{tile_cell}.independent_reference.cdl"
    write_tile_reference(tile_ref, tile_cell=tile_cell)
    tile_log = lvs_dir / f"{tile_cell}.netgen_lvs.log"
    tile_stdout = lvs_dir / f"{tile_cell}.netgen_stdout.log"
    tile_status, tld, trd, tln, trn = run_netgen(
        cell=tile_cell,
        layout_spice=layout_spice,
        reference_cdl=tile_ref,
        netgen_lvs=netgen_lvs,
        netgen_setup=netgen_setup,
        log=tile_log,
        stdout=tile_stdout,
    )

    macro_layout = lvs_dir / f"{macro_cell}.layout_blackbox.spice"
    macro_ref = lvs_dir / f"{macro_cell}.reference_blackbox.cdl"
    tile_instances, tied = write_macro_blackbox_pair(
        source=source,
        layout_path=macro_layout,
        reference_path=macro_ref,
        macro_cell=macro_cell,
        macro_pins=macro_pins,
        tile_cell=tile_cell,
        tile_pins=tile_pins,
    )
    macro_log = lvs_dir / f"{macro_cell}.macro_top.netgen_lvs.log"
    macro_stdout = lvs_dir / f"{macro_cell}.macro_top.netgen_stdout.log"
    macro_status, mld, mrd, mln, mrn = run_netgen(
        cell=macro_cell,
        layout_spice=macro_layout,
        reference_cdl=macro_ref,
        netgen_lvs=netgen_lvs,
        netgen_setup=netgen_setup,
        log=macro_log,
        stdout=macro_stdout,
    )

    return (
        LvsRow(source.name, "tile", None, tile_cell, tile_status, tld, trd, tln, trn, None, {}, str(tile_log), str(tile_stdout)),
        LvsRow(source.name, "macro_top", macro_cell, tile_cell, macro_status, mld, mrd, mln, mrn, tile_instances, tied, str(macro_log), str(macro_stdout)),
    )


def write_outputs(out_dir: Path, rows: list[LvsRow]) -> None:
    status = "PASS" if rows and all(row.passed for row in rows) else "FAIL"
    counts: dict[str, int] = {}
    for row in rows:
        key = "PASS" if row.passed else "FAIL"
        counts[key] = counts.get(key, 0) + 1
    if not rows:
        counts["FAIL"] = 1
    payload = {
        "overall_status": status,
        "status_counts": counts,
        "results": [asdict(row) for row in rows],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "MANIFEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# GF180MCU 3.3V 12T 2R2W SRAM LVS Gate",
        "",
        f"- Overall status: `{status}`.",
        f"- Counts: `{counts}`.",
        "",
        "| Source | Scope | Status | Devices | Nets | Tile instances | Supply-tied signal ports |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        devices = f"{row.layout_devices}/{row.reference_devices}" if row.layout_devices is not None and row.reference_devices is not None else "unknown"
        nets = f"{row.layout_nets}/{row.reference_nets}" if row.layout_nets is not None and row.reference_nets is not None else "unknown"
        tied = ", ".join(f"{key}: {value}" for key, value in sorted(row.supply_tied_signal_ports.items()))
        tile_instances = "" if row.tile_instances is None else str(row.tile_instances)
        lines.append(f"| `{row.source}` | `{row.scope}` | `{row.status}` | `{devices}` | `{nets}` | {tile_instances} | `{tied or 'none'}` |")
    lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-reports", type=Path, default=default_reports_path())
    parser.add_argument("--out-dir", type=Path, default=Path("verification/results/gf180mcu_3v3_12t_2r2w_sram_lvs_gate"))
    parser.add_argument("--netgen-lvs", default="netgen-lvs")
    parser.add_argument("--netgen-setup", type=Path, default=None)
    parser.add_argument("--macro-cell", default=None)
    parser.add_argument("--tile-cell", default=None)
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args(argv)
    netgen_setup = require_path(
        args.netgen_setup or pdk_file_from_env("netgen"),
        description="GF180 Netgen setup",
        option="--netgen-setup",
    )

    sources = read_sources(args.source_reports)
    if not sources:
        raise SystemExit(f"no .current_pdk.spice files found under {args.source_reports}")

    rows: list[LvsRow] = []
    had_error = False
    for source in sources:
        try:
            tile_row, macro_row = check_source(
                source=source,
                out_dir=args.out_dir,
                netgen_lvs=args.netgen_lvs,
                netgen_setup=netgen_setup,
                preferred_macro=args.macro_cell,
                preferred_tile=args.tile_cell,
            )
        except Exception as exc:
            had_error = True
            print(f"[ERROR] {source.name}: {exc}", file=sys.stderr)
            if not args.keep_going:
                break
            continue
        rows.extend([tile_row, macro_row])
        for row in (tile_row, macro_row):
            status = "PASS" if row.passed else "FAIL"
            tied = ", ".join(f"{key}: {value}" for key, value in sorted(row.supply_tied_signal_ports.items()))
            print(
                f"[{status}] {row.source} {row.scope}: LVS={row.status}, "
                f"devices={row.layout_devices}/{row.reference_devices}, "
                f"nets={row.layout_nets}/{row.reference_nets}, tied={tied or 'none'}"
            )
        if (not tile_row.passed or not macro_row.passed) and not args.keep_going:
            break

    write_outputs(args.out_dir, rows)
    return 1 if had_error or any(not row.passed for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
