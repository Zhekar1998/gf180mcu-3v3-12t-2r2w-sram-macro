# Column Periphery Gate

| Macro | Check | Status | Detail | Evidence |
| --- | --- | --- | --- | --- |
| `column_periphery` | `placement manifest status` | `PASS` | status=PASS | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `column leaf instance count` | `PASS` | instances={'precharge_sense': 16, 'write_driver': 16} expected_total=32 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `expanded wrapper height` | `PASS` | old=340.92 new=389.8 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `phase row assignment` | `PASS` | read=1 write=1 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `column leaf instance count` | `PASS` | instances={'precharge_sense': 64, 'write_driver': 64} expected_total=128 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `expanded wrapper height` | `PASS` | old=618.04 new=752.71 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `phase row assignment` | `PASS` | read=2 write=2 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `column leaf instance count` | `PASS` | instances={'precharge_sense': 16, 'write_driver': 16} expected_total=32 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `expanded wrapper height` | `PASS` | old=618.04 new=666.92 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `phase row assignment` | `PASS` | read=1 write=1 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `column leaf instance count` | `PASS` | instances={'precharge_sense': 64, 'write_driver': 64} expected_total=128 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `expanded wrapper height` | `PASS` | old=1172.28 new=1306.95 | `reports/column_periphery_integration/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `phase row assignment` | `PASS` | read=2 write=2 | `reports/column_periphery_integration/MANIFEST.json` |
| `column_periphery` | `GDS manifest status` | `PASS` | status=PASS | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `column_periphery` | `512x8 GF180 main.drc smoke` | `PASS` | violations=0 report=reports/column_periphery_gds_merge/gf180mcu_3v3_12t_2r2w_sram_512x8/main_drc.lyrdb | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `GDS wrapper merge` | `PASS` | bbox={'left_um': 0.0, 'bottom_um': 0.0, 'right_um': 594.64, 'top_um': 389.8, 'width_um': 594.64, 'height_um': 389.8} | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `leaf cells present in top` | `PASS` | leaf_count=32 expected=32 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `route cell present` | `PASS` | route_cell=gf180mcu_3v3_12t_2r2w_sram_512x8_column_periphery_routes shapes=729 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `route cell dummy fill disabled` | `PASS` | density_fill_shapes=0 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x8` | `M5 VDD/VSS short audit` | `PASS` | short_count=0 m5_regions=4403 labels=514 | `verification/results/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate/gf180mcu_3v3_12t_2r2w_sram_512x8.m5_power_short_audit.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `GDS wrapper merge` | `PASS` | bbox={'left_um': 0.0, 'bottom_um': 0.0, 'right_um': 1019.545, 'top_um': 752.71, 'width_um': 1019.545, 'height_um': 752.71} | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `leaf cells present in top` | `PASS` | leaf_count=128 expected=128 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `route cell present` | `PASS` | route_cell=gf180mcu_3v3_12t_2r2w_sram_512x32_column_periphery_routes shapes=2930 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `route cell dummy fill disabled` | `PASS` | density_fill_shapes=0 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_512x32` | `M5 VDD/VSS short audit` | `PASS` | short_count=0 m5_regions=17508 labels=2050 | `verification/results/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate/gf180mcu_3v3_12t_2r2w_sram_512x32.m5_power_short_audit.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `GDS wrapper merge` | `PASS` | bbox={'left_um': 0.0, 'bottom_um': 0.0, 'right_um': 594.64, 'top_um': 666.92, 'width_um': 594.64, 'height_um': 666.92} | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `leaf cells present in top` | `PASS` | leaf_count=32 expected=32 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `route cell present` | `PASS` | route_cell=gf180mcu_3v3_12t_2r2w_sram_1024x8_column_periphery_routes shapes=729 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `route cell dummy fill disabled` | `PASS` | density_fill_shapes=0 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x8` | `M5 VDD/VSS short audit` | `PASS` | short_count=0 m5_regions=8771 labels=1026 | `verification/results/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate/gf180mcu_3v3_12t_2r2w_sram_1024x8.m5_power_short_audit.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `GDS wrapper merge` | `PASS` | bbox={'left_um': 0.0, 'bottom_um': 0.0, 'right_um': 1019.545, 'top_um': 1306.95, 'width_um': 1019.545, 'height_um': 1306.95} | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `leaf cells present in top` | `PASS` | leaf_count=128 expected=128 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `route cell present` | `PASS` | route_cell=gf180mcu_3v3_12t_2r2w_sram_1024x32_column_periphery_routes shapes=2930 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `route cell dummy fill disabled` | `PASS` | density_fill_shapes=0 | `reports/column_periphery_gds_merge/MANIFEST.json` |
| `gf180mcu_3v3_12t_2r2w_sram_1024x32` | `M5 VDD/VSS short audit` | `PASS` | short_count=0 m5_regions=34948 labels=4098 | `verification/results/gf180mcu_3v3_12t_2r2w_sram_column_periphery_gate/gf180mcu_3v3_12t_2r2w_sram_1024x32.m5_power_short_audit.json` |
