#!/usr/bin/env python3
"""Run blackbox macro-top Netgen LVS on extracted SPICE from published reports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from gf180mcu_3v3_12t_2r2w_sram_lvs_common import pdk_file_from_env, require_path, run_netgen_lvs
from gf180mcu_3v3_12t_2r2w_sram_tile_lvs import PUBLIC_TILE_CELL, SpiceSource, default_reports_path, logical_spice_lines, read_sources, safe_name


SUPPLY_PORTS = {"VDD", "VSS", "VSUBS"}


@dataclass(frozen=True)
class MacroTopLvsResult:
    source: str
    macro_cell: str
    tile_cell: str
    status: str
    layout_devices: int | None
    reference_devices: int | None
    layout_nets: int | None
    reference_nets: int | None
    tile_instances: int
    supply_tied_signal_ports: dict[str, int]
    layout_blackbox_spice: str
    reference_blackbox_cdl: str
    netgen_lvs_log: str
    netgen_stdout_log: str

    @property
    def failed(self) -> bool:
        return self.status not in {"match", "match_unique"}


def subckt_headers(text: str) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for line in logical_spice_lines(text):
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt":
            headers[fields[1]] = fields[2:]
    return headers


def extract_subckt_lines(text: str, cell: str) -> tuple[list[str], list[str]]:
    raw_lines = text.splitlines()
    start = None
    for idx, raw in enumerate(raw_lines):
        fields = raw.strip().split()
        if len(fields) >= 2 and fields[0].lower() == ".subckt" and fields[1] == cell:
            start = idx
            break
    if start is None:
        raise RuntimeError(f"missing .subckt {cell}")

    end = None
    for idx in range(start + 1, len(raw_lines)):
        if raw_lines[idx].strip().lower().startswith(".ends"):
            end = idx
            break
    if end is None:
        raise RuntimeError(f"unterminated .subckt {cell}")

    block = raw_lines[start : end + 1]
    pins: list[str] = []
    for idx, raw in enumerate(block):
        text_line = raw.strip()
        if idx == 0:
            pins.extend(text_line.split()[2:])
            continue
        if text_line.startswith("+"):
            pins.extend(text_line[1:].split())
            continue
        break
    return block, pins


def body_logical_lines(block: list[str]) -> list[str]:
    text = "\n".join(block[1:-1])
    return logical_spice_lines(text)


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


def write_empty_subckt(lines: list[str], *, cell: str, pins: list[str]) -> None:
    lines.extend(format_line([".subckt", cell, *pins]))
    lines.append(f".ends {cell}")


def identify_cells(source: SpiceSource, preferred_macro: str | None, preferred_tile: str | None) -> tuple[str, str, list[str], list[str]]:
    headers = subckt_headers(source.text)
    if preferred_tile:
        tile_cell = preferred_tile
    elif PUBLIC_TILE_CELL in headers:
        tile_cell = PUBLIC_TILE_CELL
    else:
        tile_matches = [
            cell
            for cell in headers
            if "12t" in cell
            and "4x4" in cell
            and ("tile" in cell or "routed_5layer_direct" in cell)
        ]
        if len(tile_matches) != 1:
            raise RuntimeError(f"could not identify tile cell in {source.name}")
        tile_cell = tile_matches[0]
    if tile_cell not in headers:
        raise RuntimeError(f"missing tile cell {tile_cell}")

    if preferred_macro:
        macro_cell = preferred_macro
    else:
        macro_matches = [cell for cell in headers if cell != tile_cell]
        if len(macro_matches) != 1:
            raise RuntimeError(f"could not identify macro cell in {source.name}: {macro_matches}")
        macro_cell = macro_matches[0]
    if macro_cell not in headers:
        raise RuntimeError(f"missing macro cell {macro_cell}")
    return macro_cell, tile_cell, headers[macro_cell], headers[tile_cell]


def tile_instance_lines(macro_block: list[str], tile_cell: str) -> list[list[str]]:
    instances: list[list[str]] = []
    for line in body_logical_lines(macro_block):
        fields = line.split()
        if fields and fields[0].startswith("X") and fields[-1] == tile_cell:
            instances.append(fields)
    if not instances:
        raise RuntimeError(f"no instances of {tile_cell}")
    return instances


def expected_net(instance_name: str, port: str) -> str:
    if port in SUPPLY_PORTS:
        return port
    return f"{instance_name[1:]}/{port}"


def write_blackbox_netlists(
    *,
    source: SpiceSource,
    layout_path: Path,
    reference_path: Path,
    macro_cell: str,
    macro_pins: list[str],
    tile_cell: str,
    tile_pins: list[str],
) -> tuple[int, dict[str, int]]:
    macro_block, _ = extract_subckt_lines(source.text, macro_cell)
    instances = tile_instance_lines(macro_block, tile_cell)

    layout_lines = [f"* Layout macro-top blackbox extracted from {source.name}", ""]
    write_empty_subckt(layout_lines, cell=tile_cell, pins=tile_pins)
    layout_lines.append("")
    layout_lines.extend(format_line([".subckt", macro_cell, *macro_pins]))

    reference_lines = [f"* Independent macro-top blackbox reference for {source.name}", ""]
    write_empty_subckt(reference_lines, cell=tile_cell, pins=tile_pins)
    reference_lines.append("")
    reference_lines.extend(format_line([".subckt", macro_cell, *macro_pins]))

    tied: dict[str, int] = {}
    for fields in instances:
        instance_name = fields[0]
        nets = fields[1:-1]
        if len(nets) != len(tile_pins):
            raise RuntimeError(
                f"{instance_name}: expected {len(tile_pins)} tile nets, got {len(nets)}"
            )
        layout_lines.extend(format_line(fields))

        reference_nets = []
        for port, net in zip(tile_pins, nets, strict=True):
            if port not in SUPPLY_PORTS and net in {"VDD", "VSS"}:
                key = f"{port}->{net}"
                tied[key] = tied.get(key, 0) + 1
            reference_nets.append(expected_net(instance_name, port))
        reference_lines.extend(format_line([instance_name, *reference_nets, tile_cell]))

    layout_lines.append(f".ends {macro_cell}")
    reference_lines.append(f".ends {macro_cell}")
    layout_path.write_text("\n".join(layout_lines) + "\n")
    reference_path.write_text("\n".join(reference_lines) + "\n")
    return len(instances), tied


def run_one(
    *,
    source: SpiceSource,
    preferred_macro: str | None,
    preferred_tile: str | None,
    out_dir: Path,
    netgen_lvs: str,
    netgen_setup: Path,
) -> MacroTopLvsResult:
    macro_cell, tile_cell, macro_pins, tile_pins = identify_cells(source, preferred_macro, preferred_tile)
    target_dir = out_dir / safe_name(source.name)
    lvs_dir = target_dir / "lvs"
    lvs_dir.mkdir(parents=True, exist_ok=True)

    layout_blackbox = lvs_dir / f"{macro_cell}.layout_blackbox.spice"
    reference_blackbox = lvs_dir / f"{macro_cell}.reference_blackbox.cdl"
    tile_instances, tied = write_blackbox_netlists(
        source=source,
        layout_path=layout_blackbox,
        reference_path=reference_blackbox,
        macro_cell=macro_cell,
        macro_pins=macro_pins,
        tile_cell=tile_cell,
        tile_pins=tile_pins,
    )
    lvs_log = lvs_dir / f"{macro_cell}.macro_top.netgen_lvs.log"
    stdout_log = lvs_dir / f"{macro_cell}.macro_top.netgen_stdout.log"
    status, layout_devices, reference_devices, layout_nets, reference_nets = run_netgen_lvs(
        tile_cell=macro_cell,
        layout_spice=layout_blackbox,
        reference_cdl=reference_blackbox,
        netgen_lvs=netgen_lvs,
        netgen_setup=netgen_setup,
        lvs_log=lvs_log,
        stdout_log=stdout_log,
    )
    return MacroTopLvsResult(
        source=source.name,
        macro_cell=macro_cell,
        tile_cell=tile_cell,
        status=status,
        layout_devices=layout_devices,
        reference_devices=reference_devices,
        layout_nets=layout_nets,
        reference_nets=reference_nets,
        tile_instances=tile_instances,
        supply_tied_signal_ports=tied,
        layout_blackbox_spice=str(layout_blackbox),
        reference_blackbox_cdl=str(reference_blackbox),
        netgen_lvs_log=str(lvs_log),
        netgen_stdout_log=str(stdout_log),
    )


def write_manifest(out_dir: Path, results: list[MacroTopLvsResult]) -> None:
    payload = {
        "status": "PASS" if not any(result.failed for result in results) else "FAIL",
        "results": [asdict(result) for result in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "MANIFEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Report Macro-Top Blackbox LVS",
        "",
        "| Source | Status | Tile instances | Devices | Nets | Supply-tied signal ports |",
        "| --- | --- | ---: | ---: | ---: | --- |",
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
        tied = ", ".join(f"{port}: {count}" for port, count in sorted(result.supply_tied_signal_ports.items()))
        lines.append(
            f"| `{result.source}` | `{result.status}` | {result.tile_instances} | `{devices}` | `{nets}` | `{tied or 'none'}` |"
        )
    lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=default_reports_path())
    parser.add_argument("--macro-cell", default=None)
    parser.add_argument("--tile-cell", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("verification/results/gf180mcu_3v3_12t_2r2w_sram_macro_lvs"))
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

    results: list[MacroTopLvsResult] = []
    had_error = False
    for source in sources:
        try:
            result = run_one(
                source=source,
                preferred_macro=args.macro_cell,
                preferred_tile=args.tile_cell,
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
        tied = ", ".join(f"{port}: {count}" for port, count in sorted(result.supply_tied_signal_ports.items()))
        print(
            f"[{status}] {source.name}: LVS={result.status}, "
            f"tiles={result.tile_instances}, devices={result.layout_devices}/{result.reference_devices}, "
            f"nets={result.layout_nets}/{result.reference_nets}, tied={tied or 'none'}"
        )
        if result.failed and not args.keep_going:
            break

    write_manifest(args.out_dir, results)
    return 1 if had_error or any(result.failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
