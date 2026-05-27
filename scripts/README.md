# Generator Scripts

This directory is a release-facing snapshot of the macro generator entrypoints used by the package build.
It is included for review and reproducibility; the full Detronyx workspace is still required for local regeneration.

Primary source-workspace targets:

```bash
make build-gf180mcu-3v3-12t-2r2w-sram-array-macros
make build-gf180mcu-3v3-12t-2r2w-sram-periphery-leaves
make build-gf180mcu-3v3-12t-2r2w-sram-final-physical
python3 scripts/integrate_gf180mcu_3v3_12t_2r2w_sram_stdcell_control.py
python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_stdcell_control.py
klayout -b -r scripts/rewrite_gf180mcu_3v3_12t_2r2w_sram_gds_topcells.rb
klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_stdcell_gds.rb
python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_row_select_stdcells.py
klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_row_select_gds.rb
klayout -b -r scripts/route_gf180mcu_3v3_12t_2r2w_sram_control_signals.rb
python3 scripts/place_gf180mcu_3v3_12t_2r2w_sram_column_periphery.py
klayout -b -r scripts/merge_gf180mcu_3v3_12t_2r2w_sram_column_periphery_gds.rb
python3 verification/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate.py
python3 verification/gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate.py
python3 scripts/run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py --timeout-sec 900 --no-rc --out-dir reports/full_gds_lvs_pex_no_rc_all
python3 scripts/run_gf180mcu_3v3_12t_2r2w_sram_local_signoff.py \
  --final-manifest reports/final_physical/MANIFEST.json \
  --primitive-manifest reports/control_leaf_library/MANIFEST.json \
  --out-dir reports/local_signoff_full \
  --magic-rc /path/to/gf180mcuD.magicrc \
  --gf180-klayout-drc-dir /path/to/gf180mcuD/libs.tech/klayout/drc
make package-gf180mcu-3v3-12t-2r2w-sram-macro
```

Release script names in this package:

- `build_gf180mcu_3v3_12t_2r2w_sram_periphery_slice.py`
- `build_gf180mcu_3v3_12t_2r2w_sram_periphery_leaves.py` - compact standalone DRC/LVS-clean periphery leaf generator, including x32 tile-pitch-compatible write-driver and precharge/sense column leaf generation.
- `integrate_gf180mcu_3v3_12t_2r2w_sram_stdcell_control.py`
- `place_gf180mcu_3v3_12t_2r2w_sram_stdcell_control.py`
- `rewrite_gf180mcu_3v3_12t_2r2w_sram_gds_topcells.rb`
- `merge_gf180mcu_3v3_12t_2r2w_sram_stdcell_gds.rb`
- `place_gf180mcu_3v3_12t_2r2w_sram_row_select_stdcells.py`
- `merge_gf180mcu_3v3_12t_2r2w_sram_row_select_gds.rb`
- `route_gf180mcu_3v3_12t_2r2w_sram_control_signals.rb`
- `place_gf180mcu_3v3_12t_2r2w_sram_column_periphery.py`
- `merge_gf180mcu_3v3_12t_2r2w_sram_column_periphery_gds.rb`
- `audit_gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment.rb` - KLayout GDS audit that checks row-select WL/RWL and column-periphery pin centers land on their routed shapes, rejects manual dummy fill/poly in route cells, and rejects legacy abstract M4 WL stubs.
- `audit_gf180mcu_3v3_12t_2r2w_sram_m5_power_shorts.rb`
- `run_gf180mcu_3v3_12t_2r2w_sram_full_gds_lvs_pex.py` - Magic extraction/PEX directly from the published GDS wrappers, with parameterized blackbox, RC, extresist, resistor tee, net filtering, and timeout controls.
- `run_gf180mcu_3v3_12t_2r2w_sram_local_signoff.py` - mandatory packaged local gate that consumes staged LVS, physical placement/routing manifests, the pin/route alignment audit, hierarchical Magic pin/LVS extraction, full-GDS extraction/short audit, VDD/VSS RC smoke, KLayout density/antenna, and packaged ngspice proxy evidence. Magic logs are hard-gated for `Bad Device Location`, missing-device, and node-extraction diagnostics.

Packaged local signoff entrypoint:

```bash
python3 scripts/run_gf180mcu_3v3_12t_2r2w_sram_local_signoff.py \
  --final-manifest reports/final_physical/MANIFEST.json \
  --primitive-manifest reports/control_leaf_library/MANIFEST.json \
  --stdcell-control-manifest reports/stdcell_control_integration/MANIFEST.json \
  --stdcell-placement-manifest reports/stdcell_control_placement/MANIFEST.json \
  --stdcell-gds-manifest reports/stdcell_control_gds_merge/MANIFEST.json \
  --row-select-placement-manifest reports/stdcell_row_select_placement/MANIFEST.json \
  --row-select-gds-manifest reports/stdcell_row_select_gds_merge/MANIFEST.json \
  --stdcell-routing-manifest reports/stdcell_control_signal_routing/MANIFEST.json \
  --column-periphery-manifest reports/column_periphery_gds_merge/MANIFEST.json \
  --pin-route-alignment-manifest verification/results/gf180mcu_3v3_12t_2r2w_sram_pin_route_alignment_gate/MANIFEST.json \
  --full-gds-extract-manifest reports/full_gds_lvs_pex_no_rc_all/MANIFEST.json \
  --full-gds-power-rc-manifest reports/full_gds_lvs_pex_power_rc/MANIFEST.json \
  --out-dir reports/local_signoff_full \
  --magic-rc /path/to/gf180mcuD.magicrc \
  --gf180-klayout-drc-dir /path/to/gf180mcuD/libs.tech/klayout/drc
```
