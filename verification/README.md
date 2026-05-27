# Verification

This directory contains release-facing verification scripts for the published
GF180MCU 3.3V 12T 2R2W SRAM extracted-SPICE reports, plus the local 12T leaf
storage checks used before macro-level LVS/PEX work.

- `gf180mcu_3v3_12t_2r2w_sram_lvs_gate.py` runs the full release LVS gate:
  extracted 4x4 tile device LVS plus macro-top blackbox connectivity LVS.
- `gf180mcu_3v3_12t_2r2w_sram_periphery_lvs.py` gates the packaged
  transistor-level row decode/WL-driver, write-driver, precharge/sense, and
  write-conflict leaf reports.
- `gf180mcu_3v3_12t_2r2w_sram_gds_leaf_containment.py` checks whether the
  standalone periphery leaf GDS files and the published macro GDS files contain
  the expected leaf cell names.
- `gf180mcu_3v3_12t_2r2w_sram_stdcell_control_gate.py` checks that the
  vendored Avalon GF180MCU 3.3V stdcell collateral is present, that generated
  control-matrix CDLs use Avalon `INV`/`NAND`/`NOR` cells, and that macro GDS
  contains the row-select stdcell expansion.
- `gf180mcu_3v3_12t_2r2w_sram_stdcell_placement_gate.py` checks that the
  generated Avalon stdcell placement DEF/CSV files stay inside the existing
  macro footprint and do not overflow the top/bottom control bands.
- `gf180mcu_3v3_12t_2r2w_sram_stdcell_gds_gate.py` checks that the published
  macro GDS files physically contain the placed Avalon stdcell control
  instances without changing the macro footprint.
- `gf180mcu_3v3_12t_2r2w_sram_row_select_gds_gate.py` checks that custom
  row-select/WL-buffer functions are expanded into row-pitch-compatible Avalon
  stdcells, merged into macro GDS, and covered by a GF180 `main.drc` smoke run.
- `gf180mcu_3v3_12t_2r2w_sram_stdcell_control_routing_gate.py` checks that
  top-level route cells connect the expanded Avalon control/predecode netlist,
  macro address/enable pins, and row-select NAND input sinks without changing
  the macro footprint.
- `gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py` checks that the
  expanded macro GDS tops contain the array/control core, per-bit
  `precharge_sense` and `write_driver` column leaves, route cells, and the
  expected expanded wrapper dimensions.
- `gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate.py` runs a KLayout GDS
  geometry audit that checks row-select WL/RWL and column-periphery pin centers
  coincide with routed shapes, rejects dummy route-cell fill/poly, and rejects
  legacy abstract M4 WL stubs.
- `../scripts/run_gf180mcu_3v3_12t_2r2w_sram_local_signoff.py` is the packaged
  full local gate: Magic PEX, final abstract pin LVS, pin/route alignment,
  KLayout density/antenna, staged LVS evidence, Avalon control binding, and
  packaged ngspice evidence.
- `gf180mcu_3v3_12t_2r2w_sram_tile_lvs.py` checks the extracted 4x4 tile subcircuit against an
  independently generated 12T MOS reference.
- `gf180mcu_3v3_12t_2r2w_sram_macro_lvs.py` checks the macro-top tile instance connectivity
  with the tile treated as an LVS-clean blackbox.

`gf180mcu_3v3_12t_2r2w_sram_connectivity_check.py` remains a fast text tripwire for the same
macro-top failure mode, but the Netgen scripts are the real LVS checks.

These checks do not replace foundry/reference schematic LVS, full-net RC
characterization, sense-amplifier/write-driver characterization, Liberty
generation, solver-grade EM/IR, or foundry signoff.

## Release LVS

For the trust-oriented no-rebuild verification flow, run:

```bash
python3 verification/run_gf180mcu_3v3_12t_2r2w_sram_verification_only_flow.py
```

That orchestrator consumes the already-published GDS, reports, manifests, and
packaged verification decks only. It refuses generator/placer/router/merge
commands and writes one consolidated report under
`reports/verification_only_flow/`. Use `--include-full-net-rc` only when you
explicitly want the long all-net RC PEX characterization attempt; that mode
fans out independent macro RC jobs through
`verification/run_gf180mcu_3v3_12t_2r2w_sram_parallel_rc_pex.py`.

To check the published extracted SPICE, run the scripts with no positional
argument. They use the unpacked reports under `reports/`.

```bash
python3 verification/run_gf180mcu_3v3_12t_2r2w_sram_verification_only_flow.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_lvs_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_periphery_lvs.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_gds_leaf_containment.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_placement_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_gds_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_row_select_gds_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_stdcell_control_routing_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_tile_lvs.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_macro_lvs.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_connectivity_check.py
```

The packaged full local signoff report is generated under
`reports/local_signoff_full/`. The current full local status is
`{'PASS': 33, 'FAIL': 4, 'WARN': 4}`: Magic DRC, pin LVS, full-GDS no-RC
extraction/short audit, antenna, pin/route alignment, and 512x8 VDD/VSS RC
smoke pass; the four hard failures are the GF180 density deck reports after
manual route-cell dummy fill/poly was removed. Density closure is intentionally
left to a dedicated signoff fill insertion flow, not mixed into the real routing
generators.

The Netgen scripts accept `--netgen-setup`; otherwise they use
`GF180_NETGEN_SETUP`, `NETGEN_SETUP`, or the usual `GF180_PDK_ROOT` /
`PDK_ROOT` environment layout.

`gf180mcu_3v3_12t_2r2w_sram_tile_lvs.py` should pass when the 4x4 tile device
topology is clean. `gf180mcu_3v3_12t_2r2w_sram_macro_lvs.py` should pass when
the macro-top tile instance connectivity is clean. The release gate currently
passes on all four published macro variants and reports no tile signal ports
tied to `VDD` or `VSS`; the old `c3_r1_rbl` to `VSS` failure mode is kept as a
regression target by these scripts.

The periphery gate currently checks five generated Tim-derived leaf blocks:
write row decode/WL driver, read row decode/WL driver, write driver,
precharge/sense, and write-conflict control. Each leaf must have Magic DRC
`0`, Netgen LVS `match`/`match_unique`, zero disconnected pins, and the expected
pin contract, including `dout` as the SAOUT-equivalent read output.
The compact write-driver and precharge/sense leaves are also gated against the
x32 tile pitch limit of `25.950um`; the current periphery gate reports
22 pass / 0 fail. Column integration is physically present in the
published macro GDS through the expanded-wrapper column periphery gate, which
reports `{'PASS': 35}` with a 512x8 GF180 `main.drc` smoke report containing
`0` violations. The pin/route alignment gate reports `{'PASS': 16}` and checks
`13824` row-select WL/RWL points plus `3360` column-periphery route points
against the published GDS. The packaged local signoff also consumes the
full-GDS no-RC extraction/short audit for all four macro variants plus the
512x8 VDD/VSS RC smoke result.

The broad GDS containment audit still treats all five standalone Tim-derived
periphery leaves as required macro children when run with
`--require-macro-containment`. The current macro GDS intentionally contains the
column `write_driver` and `precharge_sense` leaves; row-select/WL behavior is
implemented through the Avalon stdcell expansion, and the write-conflict leaf
remains standalone collateral.

The stdcell control, placement, GDS, row-select, and control-routing gates currently pass the
vendored Avalon library, generated control-matrix CDL checks, DEF/CSV placement
checks, physical macro GDS containment for placed Avalon `INV`/`NAND`/`NOR`
control cells, row-pitch-compatible row-select/WL-buffer expansion, and top-level
M2/M3 routing of macro address/enable and predecode nets into row-select NAND inputs. The
stdcell control gate reports `{'PASS': 37}`, the placement gate reports
`{'PASS': 33}`, the row-select gate reports `{'PASS': 23}`, and the routing gate
reports `{'PASS': 18}` with a 512x8 GF180 `main.drc` smoke report containing
`0` violations.

## Leaf Storage

The leaf storage runner checks write, retention, independent dual read,
read-disturb, disabled-write hold, same-data dual write, and opposite same-cell
dual-write conflict observation on the 12T topology.

```bash
python3 verification/run_leaf_storage_checks.py
```

The generated report is written to `verification/results/README.md`. Raw
generated decks and ngspice logs are written under `verification/results/spice/`
and are intentionally git-ignored.
