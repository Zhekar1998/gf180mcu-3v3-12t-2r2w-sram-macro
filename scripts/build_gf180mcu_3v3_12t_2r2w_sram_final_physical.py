#!/usr/bin/env python3
"""Build release physical hard-macro seed abstracts for GF180MCU 12T 2R2W SRAMs.

This step emits the top-level physical hard-macro package that the rest of the
chip can place and route against: final row-edge corridor footprint, explicit
boundary pins, M4/M5 power straps, GDS, LEF, blackbox CDL, and SV collateral.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from build_gf180mcu_3v3_12t_2r2w_sram_array_macros import (
    UNITS_PER_UM,
    append_m4_m5_stack,
    parse_drc_count,
    parse_magic_power_labels,
    to_units,
)
from build_2r2w_macro_arrays import write_behavioral_model, write_decode_contract, write_spice, write_verilog
from build_physical_cells import bbox, dims_um
from extreme_compaction_search import read_magic


PUBLIC_MACROS = {
    (512, 8): "gf180mcu_3v3_12t_2r2w_sram_512x8",
    (512, 32): "gf180mcu_3v3_12t_2r2w_sram_512x32",
    (1024, 8): "gf180mcu_3v3_12t_2r2w_sram_1024x8",
    (1024, 32): "gf180mcu_3v3_12t_2r2w_sram_1024x32",
}


@dataclass(frozen=True)
class Pin:
    name: str
    direction: str
    use: str
    layer: str
    xlo: int
    ylo: int
    xhi: int
    yhi: int


@dataclass(frozen=True)
class FinalMacro:
    macro: str
    source_macro: str
    source_tile: str
    source_tile_magic: str
    source_tile_magic_sha256: str
    rows: int
    data_width: int
    physical_rows: int
    groups_per_physical_row: int
    bitcells: int
    tile_grid_rows: int
    tile_grid_cols: int
    tile_width_um: float
    tile_height_um: float
    tile_gap_um: float
    array_width_um: float
    array_height_um: float
    predecode_width_um: float
    port_strip_width_um: float
    row_edge_total_width_um: float
    control_bottom_um: float
    control_top_um: float
    width_um: float
    height_um: float
    area_mm2: float
    area_per_bit_um2: float
    max_area_mm2: float
    footprint_status: str
    pin_count: int
    drc_errors: int | None
    magic: str
    gds: str
    lef: str
    spice: str
    verilog: str
    behavioral_model: str
    decode_contract: str
    pins_json: str
    drc_log: str
    gds_log: str
    summary_md: str


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_if_different(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    shutil.copy2(src, dst)


def by_macro(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["macro"]): item for item in items}


def pin_names(rows: int, data_width: int) -> list[tuple[str, str, str]]:
    aw = (rows - 1).bit_length()
    pins: list[tuple[str, str, str]] = [
        ("clk", "INPUT", "SIGNAL"),
        ("w0_en", "INPUT", "SIGNAL"),
        ("w1_en", "INPUT", "SIGNAL"),
        ("r0_en", "INPUT", "SIGNAL"),
        ("r1_en", "INPUT", "SIGNAL"),
    ]
    for prefix in ("w0_addr", "w1_addr", "r0_addr", "r1_addr"):
        pins.extend((f"{prefix}[{idx}]", "INPUT", "SIGNAL") for idx in range(aw))
    for prefix in ("w0_data", "w1_data"):
        pins.extend((f"{prefix}[{idx}]", "INPUT", "SIGNAL") for idx in range(data_width))
    for prefix in ("r0_data", "r1_data"):
        pins.extend((f"{prefix}[{idx}]", "OUTPUT", "SIGNAL") for idx in range(data_width))
    pins.extend([("VDD", "INOUT", "POWER"), ("VSS", "INOUT", "GROUND")])
    return pins


def magic_label(lines: list[str], pin: Pin, port: int) -> None:
    x = (pin.xlo + pin.xhi) // 2
    y = (pin.ylo + pin.yhi) // 2
    lines.append(f"flabel {pin.layer.lower()} {x} {y} {x} {y} 0 FreeSans 93 0 0 0 {pin.name}")
    lines.append(f"port {port} nsew")


def add_rect(lines: list[str], layer: str, xlo: int, ylo: int, xhi: int, yhi: int) -> None:
    if xhi <= xlo or yhi <= ylo:
        return
    lines.extend([f"<< {layer.lower()} >>", f"rect {xlo} {ylo} {xhi} {yhi}"])


def add_fill_grid(
    lines: list[str],
    *,
    layer: str,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    pitch: int,
    fill: int,
) -> None:
    y = y0
    while y + fill <= y1:
        x = x0
        while x + fill <= x1:
            add_rect(lines, layer, x, y, x + fill, y + fill)
            x += pitch
        y += pitch


def add_density_fill(
    lines: list[str],
    *,
    width: int,
    height: int,
    row_edge_width: int,
    control_bottom: int,
    control_top: int,
    include_density_fill: bool,
    include_drawn_poly: bool,
) -> None:
    """Add floating dummy fill on GF180 fill datatypes for local density decks."""
    if not include_density_fill:
        return
    pitch = to_units(14.0)
    fill = to_units(8.0)
    margin = to_units(1.0)
    for layer in ("fillm1", "fillm2", "fillm3", "fillm4", "fillm5"):
        add_fill_grid(lines, layer=layer, x0=margin, y0=margin, x1=width - margin, y1=height - margin, pitch=pitch, fill=fill)

    if not include_drawn_poly:
        return

    # GF180 density.drc checks drawn POLY (30/0), not POLYFILL (30/4), for
    # PL.8.  Keep this floating poly in top-level corridors outside the bitcell
    # array so it cannot cross active and accidentally create devices.  This is
    # used only for the filled GDS source, not for the Magic source used by
    # PEX/LVS, because extracted floating poly nets are irrelevant to macro-top
    # connectivity LVS but still perturb Netgen net counts.
    poly_fill = to_units(12.0)
    poly_windows = (
        (margin, margin, max(margin, row_edge_width - margin), height - margin),
        (row_edge_width + margin, margin, width - margin, max(margin, control_bottom - margin)),
        (row_edge_width + margin, height - control_top + margin, width - margin, height - margin),
    )
    for x0, y0, x1, y1 in poly_windows:
        add_fill_grid(lines, layer="poly", x0=x0, y0=y0, x1=x1, y1=y1, pitch=pitch, fill=poly_fill)


def create_pin(name: str, direction: str, use: str, layer: str, x: int, y: int, size: int) -> Pin:
    return Pin(name, direction, use, layer, x - size // 2, y - size // 2, x + (size + 1) // 2, y + (size + 1) // 2)


def power_rail_height(*, control_bottom: int, control_top: int, pin_size: int) -> int:
    """Return a compact rail height that leaves signal-pin access in control bands."""
    min_rail = max(pin_size, to_units(1.20))
    available = max(pin_size, min(control_bottom, control_top))
    return min(available, min_rail)


def distribute(count: int, lo: int, hi: int) -> list[int]:
    if count <= 0:
        return []
    if count == 1:
        return [(lo + hi) // 2]
    span = max(1, hi - lo)
    return [lo + int(round(span * (idx + 0.5) / count)) for idx in range(count)]


def build_pins(
    *,
    rows: int,
    data_width: int,
    width: int,
    height: int,
    row_edge_width: int,
    control_bottom: int,
    control_top: int,
    pin_size: int,
) -> list[Pin]:
    names = pin_names(rows, data_width)
    signal_names = [item for item in names if item[2] == "SIGNAL"]
    ctrl_addr = [item for item in signal_names if "_data[" not in item[0]]
    wdata = [item for item in signal_names if item[0].startswith(("w0_data", "w1_data"))]
    rdata = [item for item in signal_names if item[0].startswith(("r0_data", "r1_data"))]
    rail_h = power_rail_height(control_bottom=control_bottom, control_top=control_top, pin_size=pin_size)

    pins: list[Pin] = []
    y_positions = distribute(len(ctrl_addr), control_bottom + pin_size, height - control_top - pin_size)
    ctrl_x = max(pin_size, min(row_edge_width - pin_size, pin_size))
    for (name, direction, use), y in zip(ctrl_addr, y_positions):
        pins.append(create_pin(name, direction, use, "Metal4", ctrl_x, y, pin_size))

    data_lo = row_edge_width + pin_size
    data_hi = width - pin_size
    write_y = height - max(rail_h + pin_size, control_top // 2)
    read_y = max(rail_h + pin_size, control_bottom // 2)
    for (name, direction, use), x in zip(wdata, distribute(len(wdata), data_lo, data_hi)):
        pins.append(create_pin(name, direction, use, "Metal5", x, write_y, pin_size))
    for (name, direction, use), x in zip(rdata, distribute(len(rdata), data_lo, data_hi)):
        pins.append(create_pin(name, direction, use, "Metal5", x, read_y, pin_size))

    pins.append(Pin("VDD", "INOUT", "POWER", "Metal5", 0, height - rail_h, width, height))
    pins.append(Pin("VSS", "INOUT", "GROUND", "Metal5", 0, 0, width, rail_h))
    return pins


def write_top_magic(
    path: Path,
    *,
    macro: str,
    source_macro: str,
    tile_cell: str,
    tech: str,
    magscale: str,
    tile_bbox: tuple[int, int, int, int],
    tile_w: int,
    tile_h: int,
    tile_pitch_x: int,
    tile_pitch_y: int,
    tile_grid_rows: int,
    tile_grid_cols: int,
    tile_power_pins: dict[str, tuple[int, int]],
    row_edge_width: int,
    port_strip_width: int,
    predecode_width: int,
    control_bottom: int,
    control_top: int,
    width: int,
    height: int,
    physical_rows: int,
    pins: list[Pin],
    include_density_fill: bool = False,
    include_drawn_poly_fill: bool = False,
) -> None:
    xlo, ylo, xhi, yhi = tile_bbox
    lines = [
        "magic",
        f"tech {tech}",
        f"magscale {magscale}",
        "timestamp 1780039000",
    ]

    for tile_row in range(tile_grid_rows):
        for tile_col in range(tile_grid_cols):
            x = row_edge_width + tile_col * tile_pitch_x
            y = control_bottom + tile_row * tile_pitch_y
            inst = f"u_t{tile_row:03d}_{tile_col:03d}"
            lines.extend(
                [
                    f"use {tile_cell} {inst}",
                    "timestamp 1780023000",
                    f"transform 1 0 {x} 0 1 {y}",
                    f"box {xlo} {ylo} {xhi} {yhi}",
                ]
            )

    y0 = control_bottom
    y1 = height - control_top

    # WL landing stubs at the physical row pitch.  These are pin-access tracks
    # for the final dense row-select device strip.  Keep them isolated per port;
    # broad blanket conductors here shorted all external control pins to the
    # power rails during pin-LVS.
    wl_pitch = max(1, (y1 - y0) // max(1, physical_rows))
    stub_h = max(1, to_units(0.12))
    lane_margin = max(1, min(to_units(0.20), max(1, port_strip_width // 5)))
    for row in range(physical_rows):
        y = y0 + row * wl_pitch + wl_pitch // 2
        for idx in range(4):
            sx0 = predecode_width + idx * port_strip_width + lane_margin
            sx1 = predecode_width + (idx + 1) * port_strip_width - lane_margin
            add_rect(lines, "metal4", sx0, y - stub_h, sx1, y + stub_h)

    # Top/bottom power trunks and per-column M4 ties, same strategy as the
    # verified shell generator.
    rail_h = power_rail_height(control_bottom=control_bottom, control_top=control_top, pin_size=max(1, pins[0].xhi - pins[0].xlo))
    add_rect(lines, "metal5", 0, height - rail_h, width, height)
    add_rect(lines, "metal5", 0, 0, width, rail_h)
    add_rect(lines, "metal4", 0, height - rail_h, width, height)
    add_rect(lines, "metal4", 0, 0, width, rail_h)
    if {"VDD", "VSS"} <= set(tile_power_pins):
        vdd_local_x, vdd_local_y = tile_power_pins["VDD"]
        vss_local_x, vss_local_y = tile_power_pins["VSS"]
        m4_w = to_units(0.34)
        m5_w = to_units(0.42)
        top_y = height - rail_h // 2
        bottom_y = rail_h // 2
        array_x0 = row_edge_width
        array_x1 = row_edge_width + (tile_grid_cols - 1) * tile_pitch_x + tile_w
        pin_size = max(1, pins[0].xhi - pins[0].xlo)
        if predecode_width > 4 * pin_size:
            vss_bus_x = predecode_width // 2
        else:
            vss_bus_x = max(pin_size, row_edge_width // 4)
        vss_bus_top = control_bottom + (tile_grid_rows - 1) * tile_pitch_y + vss_local_y
        add_rect(lines, "metal4", vss_bus_x - m4_w // 2, bottom_y, vss_bus_x + (m4_w + 1) // 2, vss_bus_top)
        append_m4_m5_stack(lines, vss_bus_x, bottom_y)
        for tile_col in range(tile_grid_cols):
            col_x = row_edge_width + tile_col * tile_pitch_x
            vdd_x = col_x + vdd_local_x
            add_rect(lines, "metal4", vdd_x - m4_w // 2, control_bottom + vdd_local_y, vdd_x + (m4_w + 1) // 2, top_y)
            append_m4_m5_stack(lines, vdd_x, top_y)
            for tile_row in range(tile_grid_rows):
                row_y = control_bottom + tile_row * tile_pitch_y
                append_m4_m5_stack(lines, vdd_x, row_y + vdd_local_y)
        for tile_row in range(tile_grid_rows):
            row_y = control_bottom + tile_row * tile_pitch_y
            vss_y = row_y + vss_local_y
            add_rect(lines, "metal5", vss_bus_x, vss_y - m5_w // 2, array_x1, vss_y + (m5_w + 1) // 2)
            append_m4_m5_stack(lines, vss_bus_x, vss_y)

    add_density_fill(
        lines,
        width=width,
        height=height,
        row_edge_width=row_edge_width,
        control_bottom=control_bottom,
        control_top=control_top,
        include_density_fill=include_density_fill,
        include_drawn_poly=include_drawn_poly_fill,
    )

    for pin in pins:
        add_rect(lines, pin.layer.lower(), pin.xlo, pin.ylo, pin.xhi, pin.yhi)

    lines.append("<< labels >>")
    for port, pin in enumerate(pins, start=1):
        magic_label(lines, pin, port)

    lines.extend(
        [
            "<< properties >>",
            f"string FIXED_BBOX 0 0 {width} {height}",
            f"string DETRONYX_PHYSICAL_MACRO {macro}",
            f"string DETRONYX_SOURCE_MACRO {source_macro}",
            f"string DETRONYX_SOURCE_TILE {tile_cell}",
            "string DETRONYX_MACRO_STATUS rc7f_final_physical_hardmacro",
            "string DETRONYX_CONTROL_STATUS physical_row_edge_corridors_rc7_structural_cdl_bound",
            "string DETRONYX_ROUTE_STYLE rc7f_row_edge_m3_m4_m5_pin_access",
            f"string DETRONYX_ROW_EDGE_WIDTH_UNITS {row_edge_width}",
            f"string DETRONYX_PORT_STRIP_WIDTH_UNITS {port_strip_width}",
            f"string DETRONYX_PREDECODE_WIDTH_UNITS {predecode_width}",
            f"string DETRONYX_PHYSICAL_ROWS {physical_rows}",
            "<< end >>",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def write_drc_tcl(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "crashbackups stop",
                "set topcell $::env(MAGIC_TOPCELL)",
                "load $topcell",
                "select top cell",
                "drc on",
                "drc style drc(full)",
                "drc check",
                "drc count total",
                "drc listall why",
                "quit -noprompt",
            ]
        )
        + "\n"
    )


def write_gds_tcl(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "crashbackups stop",
                "drc off",
                "set topcell $::env(MAGIC_TOPCELL)",
                "load $topcell",
                "select top cell",
                "gds write ../layout/$topcell.gds",
                "quit -noprompt",
            ]
        )
        + "\n"
    )


def run_magic(*, macro: str, magic_dir: Path, script: Path, log_path: Path, magic: str, magic_rc: Path) -> int | None:
    env = os.environ.copy()
    env["MAGIC_TOPCELL"] = macro
    proc = subprocess.run(
        [magic, "-dnull", "-noconsole", "-rcfile", str(magic_rc)],
        cwd=magic_dir,
        input=script.read_text(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        check=False,
    )
    log_path.write_text(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError(f"Magic failed for {macro}; see {log_path}")
    return parse_drc_count(proc.stdout)


def run_magic_gds(
    *,
    macro: str,
    magic_dir: Path,
    script: Path,
    log_path: Path,
    magic: str,
    magic_rc: Path,
    gds_path: Path,
    timeout_seconds: float = 1800.0,
) -> None:
    if gds_path.exists():
        gds_path.unlink()
    env = os.environ.copy()
    env["MAGIC_TOPCELL"] = macro
    proc = subprocess.run(
        [magic, "-dnull", "-noconsole", "-rcfile", str(magic_rc)],
        cwd=magic_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        input=script.read_text(),
        env=env,
        timeout=timeout_seconds,
        check=False,
    )
    log_path.write_text(proc.stdout)
    if not gds_path.exists() or gds_path.stat().st_size == 0:
        raise RuntimeError(f"Magic GDS failed for {macro}; see {log_path}")
    if proc.returncode != 0:
        raise RuntimeError(f"Magic GDS failed for {macro}; see {log_path}")
    if gds_path.read_bytes()[-4:] != b"\x00\x04\x04\x00":
        raise RuntimeError(f"Magic GDS for {macro} is missing ENDLIB; see {log_path}")


def write_lef(path: Path, macro: str, width_um: float, height_um: float, pins: list[Pin]) -> None:
    lines = [
        "VERSION 5.8 ;",
        'BUSBITCHARS "[]" ;',
        'DIVIDERCHAR "/" ;',
        f"MACRO {macro}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {macro} 0.000 0.000 ;",
        "  ORIGIN 0.000 0.000 ;",
        f"  SIZE {width_um:.6f} BY {height_um:.6f} ;",
        "  SYMMETRY X Y ;",
    ]
    for pin in pins:
        lines.extend(
            [
                f"  PIN {pin.name}",
                f"    DIRECTION {pin.direction} ;",
                f"    USE {pin.use} ;",
                "    PORT",
                f"      LAYER {pin.layer} ;",
                (
                    f"        RECT {pin.xlo / UNITS_PER_UM:.6f} {pin.ylo / UNITS_PER_UM:.6f} "
                    f"{pin.xhi / UNITS_PER_UM:.6f} {pin.yhi / UNITS_PER_UM:.6f} ;"
                ),
                "    END",
                f"  END {pin.name}",
            ]
        )
    lines.extend(
        [
            "  OBS",
            "    LAYER Metal1 ;",
            f"      RECT 0.000000 0.000000 {width_um:.6f} {height_um:.6f} ;",
            "    LAYER Metal2 ;",
            f"      RECT 0.000000 0.000000 {width_um:.6f} {height_um:.6f} ;",
            "  END",
            f"END {macro}",
            "END LIBRARY",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def write_pins_json(path: Path, pins: list[Pin]) -> None:
    payload = []
    for pin in pins:
        payload.append(
            {
                "name": pin.name,
                "direction": pin.direction,
                "use": pin.use,
                "layer": pin.layer,
                "rect_um": [
                    round(pin.xlo / UNITS_PER_UM, 6),
                    round(pin.ylo / UNITS_PER_UM, 6),
                    round(pin.xhi / UNITS_PER_UM, 6),
                    round(pin.yhi / UNITS_PER_UM, 6),
                ],
            }
        )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def build_one(args: argparse.Namespace, array: dict[str, Any], budget: dict[str, Any]) -> FinalMacro:
    source_macro = str(array["macro"])
    rows = int(array["rows"])
    data_width = int(array["data_width"])
    macro = PUBLIC_MACROS.get((rows, data_width), source_macro.replace("_rc6_fullctrl", "_rc7f_finalphys"))
    physical_rows = int(budget["physical_rows"])
    groups = int(budget["groups_per_physical_row"])
    tile_cell = str(array["source_tile"])
    source_magic = Path(str(array["magic"]))
    source_magic_dir = source_magic.parent
    source_tile_magic = args.tile_magic_override or (source_magic_dir / f"{tile_cell}.mag")
    tile_layout = read_magic(source_tile_magic, tile_cell)
    tile_magic_sha256 = sha256_file(source_tile_magic)
    tile_power_pins = parse_magic_power_labels(source_tile_magic)
    tile_box = bbox(tile_layout.rects)
    tile_w = tile_box[2] - tile_box[0]
    tile_h = tile_box[3] - tile_box[1]
    tile_width_um, tile_height_um, _tile_area = dims_um(tile_box)
    tile_gap = to_units(float(array["tile_gap_um"]))
    tile_pitch_x = tile_w + tile_gap
    tile_pitch_y = tile_h + tile_gap
    tile_grid_rows = int(array["tile_grid_rows"])
    tile_grid_cols = int(array["tile_grid_cols"])
    array_width = tile_grid_cols * tile_w + max(0, tile_grid_cols - 1) * tile_gap
    array_height = tile_grid_rows * tile_h + max(0, tile_grid_rows - 1) * tile_gap
    predecode_width = to_units(args.predecode_width_um)
    strip_width_um = float(budget["rc7_lvs_port_strip_width_um"]) if args.strip_source == "lvs" else float(budget["rc7_dense_drc_only_port_strip_width_um"])
    port_strip_width = to_units(strip_width_um)
    row_edge_width = predecode_width + 4 * port_strip_width
    control_bottom = to_units(float(array["control_bottom_um"]))
    control_top = to_units(float(array["control_top_um"]))
    width = row_edge_width + array_width
    height = control_bottom + array_height + control_top
    width_um = width / UNITS_PER_UM
    height_um = height / UNITS_PER_UM
    area_mm2 = width_um * height_um / 1_000_000.0
    bitcells = rows * data_width
    max_area = float(budget["max_area_mm2"])
    if area_mm2 <= max_area:
        footprint_status = "pass_max"
    elif area_mm2 <= max_area * 1.05:
        footprint_status = "warn_within_5pct"
    else:
        footprint_status = "fail_max"

    out_dir = args.out_dir / macro
    magic_dir = out_dir / "magic"
    gds_magic_dir = out_dir / "magic_gds"
    layout_dir = out_dir / "layout"
    abstract_dir = out_dir / "abstract"
    for directory in (magic_dir, gds_magic_dir, layout_dir, abstract_dir):
        directory.mkdir(parents=True, exist_ok=True)
    copied_tile_magic = magic_dir / f"{tile_cell}.mag"
    copy_if_different(source_tile_magic, copied_tile_magic)
    copy_if_different(source_tile_magic, gds_magic_dir / f"{tile_cell}.mag")
    pin_shapes = build_pins(
        rows=rows,
        data_width=data_width,
        width=width,
        height=height,
        row_edge_width=row_edge_width,
        control_bottom=control_bottom,
        control_top=control_top,
        pin_size=to_units(args.signal_pin_size_um),
    )
    top_magic = magic_dir / f"{macro}.mag"
    write_top_magic(
        top_magic,
        macro=macro,
        source_macro=source_macro,
        tile_cell=tile_cell,
        tech=tile_layout.tech,
        magscale=tile_layout.magscale,
        tile_bbox=tile_box,
        tile_w=tile_w,
        tile_h=tile_h,
        tile_pitch_x=tile_pitch_x,
        tile_pitch_y=tile_pitch_y,
        tile_grid_rows=tile_grid_rows,
        tile_grid_cols=tile_grid_cols,
        tile_power_pins=tile_power_pins,
        row_edge_width=row_edge_width,
        port_strip_width=port_strip_width,
        predecode_width=predecode_width,
        control_bottom=control_bottom,
        control_top=control_top,
        width=width,
        height=height,
        physical_rows=physical_rows,
        pins=pin_shapes,
        include_density_fill=False,
        include_drawn_poly_fill=False,
    )
    gds_source_magic = gds_magic_dir / f"{macro}.mag"
    write_top_magic(
        gds_source_magic,
        macro=macro,
        source_macro=source_macro,
        tile_cell=tile_cell,
        tech=tile_layout.tech,
        magscale=tile_layout.magscale,
        tile_bbox=tile_box,
        tile_w=tile_w,
        tile_h=tile_h,
        tile_pitch_x=tile_pitch_x,
        tile_pitch_y=tile_pitch_y,
        tile_grid_rows=tile_grid_rows,
        tile_grid_cols=tile_grid_cols,
        tile_power_pins=tile_power_pins,
        row_edge_width=row_edge_width,
        port_strip_width=port_strip_width,
        predecode_width=predecode_width,
        control_bottom=control_bottom,
        control_top=control_top,
        width=width,
        height=height,
        physical_rows=physical_rows,
        pins=pin_shapes,
        include_density_fill=True,
        include_drawn_poly_fill=True,
    )
    drc_tcl = gds_magic_dir / "run_drc.tcl"
    gds_tcl = gds_magic_dir / "run_gds.tcl"
    write_drc_tcl(drc_tcl)
    write_gds_tcl(gds_tcl)
    drc_log = layout_dir / f"{macro}.drc.log"
    gds_log = layout_dir / f"{macro}.gds.log"
    if args.skip_magic_drc:
        drc_log.write_text("SKIPPED: top-level Magic DRC full hierarchy is intentionally skipped for physical-seed pin iteration.\n")
        drc = None
    else:
        drc = run_magic(macro=macro, magic_dir=gds_magic_dir, script=drc_tcl, log_path=drc_log, magic=args.magic, magic_rc=args.magic_rc)
    gds = layout_dir / f"{macro}.gds"
    run_magic_gds(macro=macro, magic_dir=gds_magic_dir, script=gds_tcl, log_path=gds_log, magic=args.magic, magic_rc=args.magic_rc, gds_path=gds)
    if not gds.exists():
        raise RuntimeError(f"missing GDS: {gds}")

    lef = abstract_dir / f"{macro}.lef"
    spice = abstract_dir / f"{macro}.spice"
    verilog = abstract_dir / f"{macro}.bb.sv"
    behavioral = abstract_dir / f"{macro}.behavioral.sv"
    decode = abstract_dir / f"{macro}.decode_contract.sv"
    pins_json = abstract_dir / f"{macro}.pins.json"
    write_lef(lef, macro, width_um, height_um, pin_shapes)
    write_spice(spice, macro, rows, data_width)
    write_verilog(verilog, macro, rows, data_width)
    write_behavioral_model(behavioral, macro, rows, data_width)
    write_decode_contract(decode, macro, rows, data_width)
    write_pins_json(pins_json, pin_shapes)

    package_dir = Path("macros") / macro
    package_layout_dir = package_dir / "layout"
    package_abstract_dir = package_dir / "abstract"
    package_layout_dir.mkdir(parents=True, exist_ok=True)
    package_abstract_dir.mkdir(parents=True, exist_ok=True)
    package_gds = package_layout_dir / f"{macro}.gds"
    package_lef = package_abstract_dir / f"{macro}.lef"
    package_spice = package_abstract_dir / f"{macro}.spice"
    package_verilog = package_abstract_dir / f"{macro}.bb.sv"
    package_behavioral = package_abstract_dir / f"{macro}.behavioral.sv"
    package_decode = package_abstract_dir / f"{macro}.decode_contract.sv"
    package_pins_json = package_abstract_dir / f"{macro}.pins.json"
    for src, dst in (
        (gds, package_gds),
        (lef, package_lef),
        (spice, package_spice),
        (verilog, package_verilog),
        (behavioral, package_behavioral),
        (decode, package_decode),
        (pins_json, package_pins_json),
    ):
        shutil.copy2(src, dst)

    result = FinalMacro(
        macro=macro,
        source_macro=source_macro,
        source_tile=tile_cell,
        source_tile_magic=str(source_tile_magic),
        source_tile_magic_sha256=tile_magic_sha256,
        rows=rows,
        data_width=data_width,
        physical_rows=physical_rows,
        groups_per_physical_row=groups,
        bitcells=bitcells,
        tile_grid_rows=tile_grid_rows,
        tile_grid_cols=tile_grid_cols,
        tile_width_um=round(tile_width_um, 6),
        tile_height_um=round(tile_height_um, 6),
        tile_gap_um=float(array["tile_gap_um"]),
        array_width_um=round(array_width / UNITS_PER_UM, 6),
        array_height_um=round(array_height / UNITS_PER_UM, 6),
        predecode_width_um=round(predecode_width / UNITS_PER_UM, 6),
        port_strip_width_um=round(port_strip_width / UNITS_PER_UM, 6),
        row_edge_total_width_um=round(row_edge_width / UNITS_PER_UM, 6),
        control_bottom_um=round(control_bottom / UNITS_PER_UM, 6),
        control_top_um=round(control_top / UNITS_PER_UM, 6),
        width_um=round(width_um, 6),
        height_um=round(height_um, 6),
        area_mm2=round(area_mm2, 9),
        area_per_bit_um2=round(width_um * height_um / bitcells, 6),
        max_area_mm2=round(max_area, 6),
        footprint_status=footprint_status,
        pin_count=len(pin_shapes),
        drc_errors=drc,
        magic=str(top_magic),
        gds=str(package_gds),
        lef=str(package_lef),
        spice=str(package_spice),
        verilog=str(package_verilog),
        behavioral_model=str(package_behavioral),
        decode_contract=str(package_decode),
        pins_json=str(package_pins_json),
        drc_log=str(drc_log),
        gds_log=str(gds_log),
        summary_md=str(out_dir / "summary.md"),
    )
    write_macro_summary(out_dir / "summary.md", result)
    shutil.copy2(out_dir / "summary.md", package_dir / "summary.md")
    print(f"{macro}: {width_um:.3f}um x {height_um:.3f}um = {area_mm2:.6f}mm^2, DRC={drc}, pins={len(pin_shapes)}, {footprint_status}")
    return result


def write_macro_summary(path: Path, result: FinalMacro) -> None:
    lines = [
        f"# {result.macro} Release Physical Seed",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Source shell | `{result.source_macro}` |",
        f"| Logical shape | `{result.rows} x {result.data_width}` |",
        f"| Physical rows / groups | `{result.physical_rows}` / `{result.groups_per_physical_row}` |",
        f"| Size | `{result.width_um:.3f}um x {result.height_um:.3f}um` |",
        f"| Area | `{result.area_mm2:.6f}mm^2` |",
        f"| Area/bit | `{result.area_per_bit_um2:.3f}um^2/bit` |",
        f"| Row-edge width | `{result.row_edge_total_width_um:.3f}um` |",
        f"| Port strip width | `{result.port_strip_width_um:.3f}um` |",
        f"| Boundary pins | `{result.pin_count}` |",
        f"| Magic DRC | `{result.drc_errors}` |",
        f"| Footprint status | `{result.footprint_status}` |",
        "",
        "This is the release hard-macro physical seed for top-level integration:",
        "GDS, LEF, Magic, blackbox CDL/SV, behavioral model, decode contract,",
        "row-edge corridors, boundary pins, and M4/M5 power are emitted.",
        "",
        "Downstream package gates integrate Avalon control/row-select standard",
        "cells, column periphery leaves, and routed control/periphery shapes into",
        "the published macro GDS before local signoff.",
        "",
    ]
    path.write_text("\n".join(lines))


def write_run_summary(out_dir: Path, results: list[FinalMacro]) -> None:
    (out_dir / "MANIFEST.json").write_text(json.dumps([asdict(result) for result in results], indent=2, sort_keys=True) + "\n")
    if results:
        with (out_dir / "summary.csv").open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(FinalMacro.__dataclass_fields__.keys()))
            writer.writeheader()
            for result in results:
                writer.writerow(asdict(result))
    lines = [
        "# GF180MCU 12T 2R2W SRAM Release Physical Seed Package",
        "",
        "| Macro | Shape | Size | Area | Max | DRC | Pins | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| `{result.macro}` | `{result.rows}x{result.data_width}` | "
            f"`{result.width_um:.3f}um x {result.height_um:.3f}um` | "
            f"`{result.area_mm2:.6f}mm^2` | `{result.max_area_mm2:.6f}mm^2` | "
            f"`{result.drc_errors}` | `{result.pin_count}` | `{result.footprint_status}` |"
        )
    lines.extend(
        [
            "",
            "Generated artifacts per macro:",
            "",
            "- Magic top layout with repeated verified 4x4 tile array;",
            "- row-edge/control placement corridor geometry;",
            "- physical boundary pins for control/address/data plus VDD/VSS;",
            "- M4/M5 top-level power straps;",
            "- GDS, LEF, blackbox SPICE, blackbox SV, behavioral SV, decode contract.",
            "",
            "Final package closure is reported by the downstream stdcell,",
            "row-select, column-periphery, full-GDS extraction, and local-signoff",
            "reports.",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--array-manifest", type=Path, required=True)
    parser.add_argument("--row-edge-budget", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--magic", default="magic")
    parser.add_argument("--magic-rc", type=Path, required=True)
    parser.add_argument("--strip-source", choices=("lvs", "dense"), default="lvs")
    parser.add_argument("--predecode-width-um", type=float, default=16.0)
    parser.add_argument("--signal-pin-size-um", type=float, default=0.64)
    parser.add_argument("--macro-filter", action="append", default=[], help="Build only matching source macro name(s).")
    parser.add_argument("--skip-magic-drc", action="store_true", help="Skip heavy top-level Magic DRC; leaf/tile DRC remains covered by staged signoff.")
    parser.add_argument("--tile-magic-override", type=Path, default=None, help="Use this freshly generated 4x4 tile .mag instead of the copy embedded beside the source array shell.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    arrays = by_macro(load_json(args.array_manifest))
    budgets = by_macro(load_json(args.row_edge_budget))
    if args.macro_filter:
        allowed = set(args.macro_filter)
        budgets = {macro: item for macro, item in budgets.items() if macro in allowed}
        if not budgets:
            raise SystemExit(f"no source macros matched --macro-filter={sorted(allowed)}")
    arrays_by_shape = {
        (int(item["rows"]), int(item["data_width"])): item
        for item in arrays.values()
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for macro in sorted(budgets):
        budget = budgets[macro]
        shape = (int(budget["logical_rows"]), int(budget["data_width"]))
        if shape not in arrays_by_shape:
            raise SystemExit(f"no array source for {macro} shape {shape[0]}x{shape[1]}")
        results.append(build_one(args, arrays_by_shape[shape], budget))
    write_run_summary(args.out_dir, results)
    if args.skip_magic_drc:
        return 0
    return 0 if all(item.drc_errors == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
