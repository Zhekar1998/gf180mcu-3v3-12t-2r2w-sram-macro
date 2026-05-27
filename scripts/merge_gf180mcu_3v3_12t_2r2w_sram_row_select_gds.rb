#!/usr/bin/env ruby
# Physically merge row-select/WL-buffer stdcell expansion into macro GDS.

require "csv"
require "fileutils"
require "json"
require "rexml/document"

ROOT = File.expand_path("..", __dir__)
ROWSEL_MANIFEST = File.join(ROOT, "reports", "stdcell_row_select_placement", "MANIFEST.json")
BASE_GDS_MANIFEST = File.join(ROOT, "reports", "stdcell_control_gds_merge", "MANIFEST.json")
AVALON_GDS = File.join(
  ROOT,
  "third_party", "gf180mcu_as_sc_mcu7t3v3", "pdk", "libs.ref",
  "gf180mcu_as_sc_mcu7t3v3", "gf180mcu_as_sc_mcu7t3v3__merged.gds"
)
OUT = File.join(ROOT, "reports", "stdcell_row_select_gds_merge")
LAYER_M1 = [34, 0].freeze
LAYER_V1 = [35, 0].freeze
LAYER_M2 = [36, 0].freeze
LAYER_V2 = [38, 0].freeze
LAYER_M3 = [42, 0].freeze
LAYER_V3 = [40, 0].freeze
LAYER_M4 = [46, 0].freeze
LAYER_V4 = [41, 0].freeze
LAYER_M5 = [81, 0].freeze
GRID_UM = 0.005
ROUTE_LAYERS = [LAYER_M1, LAYER_V1, LAYER_M2, LAYER_V2, LAYER_M3, LAYER_V3, LAYER_M4, LAYER_V4, LAYER_M5].freeze
TILE_WL_LOCAL_X_UM = 0.150
TILE_WL_LOCAL_Y_UM = {
  "w0" => [0.450, 4.310, 8.170, 12.030],
  "w1" => [1.650, 5.510, 9.370, 13.230],
  "r0" => [1.000, 4.860, 8.720, 12.580],
  "r1" => [2.350, 6.210, 10.070, 13.930]
}.freeze
$shape_index = nil

def rel(path)
  path.sub("#{ROOT}/", "")
end

def find_cell(layout, name)
  if layout.respond_to?(:cell_by_name)
    begin
      value = layout.cell_by_name(name)
      return value if value.respond_to?(:name)
      return layout.cell(value) if value.is_a?(Integer) && value >= 0
    rescue StandardError
      nil
    end
  end
  begin
    value = layout.cell(name)
    return value if value.respond_to?(:name)
    return layout.cell(value) if value.is_a?(Integer) && value >= 0
  rescue StandardError
    nil
  end
  layout.each_cell { |cell| return cell if cell.name == name }
  nil
end

def dbu(layout, value_um)
  (snap_um(value_um) / layout.dbu).round
end

def dbu_raw(layout, value_um)
  (value_um.to_f / layout.dbu).round
end

def snap_um(value_um)
  (value_um.to_f / GRID_UM).round * GRID_UM
end

def layer(layout, pair)
  layout.layer(pair[0], pair[1])
end

def box_um(layout, x0, y0, x1, y1)
  RBA::Box.new(dbu(layout, x0), dbu(layout, y0), dbu(layout, x1), dbu(layout, y1))
end

def box_um_raw(layout, x0, y0, x1, y1)
  RBA::Box.new(dbu_raw(layout, x0), dbu_raw(layout, y0), dbu_raw(layout, x1), dbu_raw(layout, y1))
end

def box_key(box)
  [box.left, box.bottom, box.right, box.top].join(":")
end

def build_shape_index(cell, layout, pairs)
  index = {}
  pairs.each do |pair|
    layer_index = layer(layout, pair)
    by_box = Hash.new { |hash, key| hash[key] = [] }
    cell.shapes(layer_index).each do |shape|
      next unless shape.is_box?
      by_box[box_key(shape.box)] << shape
    end
    index[layer_index] = by_box
  end
  index
end

def delete_box(cell, layout, pair, target)
  return 0 unless $shape_index
  layer_index = layer(layout, pair)
  matches = $shape_index.fetch(layer_index, {}).delete(box_key(target)) || []
  matches.each { |shape| shape.delete }
  matches.length
end

def delete_rect(cell, layout, pair, x0, y0, x1, y1)
  deleted = 0
  deleted += delete_box(cell, layout, pair, box_um_raw(layout, x0, y0, x1, y1))
  deleted += delete_box(cell, layout, pair, box_um(layout, x0, y0, x1, y1))
  deleted
end

def add_rect(cell, layout, pair, x0, y0, x1, y1)
  return if x1 <= x0 || y1 <= y0
  # Older iterations used exact DBU rounding, which put WL tap geometry on
  # non-5nm y coordinates.  Remove both the old raw box and the current snapped
  # box so the merge can be rerun as a repair step without accumulating shapes.
  delete_box(cell, layout, pair, box_um_raw(layout, x0, y0, x1, y1))
  delete_box(cell, layout, pair, box_um(layout, x0, y0, x1, y1))
  cell.shapes(layer(layout, pair)).insert(box_um(layout, x0, y0, x1, y1))
end

def add_stack_m1_to_m4(cell, layout, x, y)
  add_rect(cell, layout, LAYER_M1, x - 0.18, y - 0.18, x + 0.18, y + 0.18)
  add_rect(cell, layout, LAYER_V1, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
  add_rect(cell, layout, LAYER_M2, x - 0.18, y - 0.18, x + 0.18, y + 0.18)
  add_rect(cell, layout, LAYER_V2, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
  add_rect(cell, layout, LAYER_M3, x - 0.18, y - 0.18, x + 0.18, y + 0.18)
  add_rect(cell, layout, LAYER_V3, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
  add_rect(cell, layout, LAYER_M4, x - 0.20, y - 0.20, x + 0.20, y + 0.20)
end

def add_stack_m4_to_m5(cell, layout, x, y)
  add_rect(cell, layout, LAYER_M4, x - 0.20, y - 0.20, x + 0.20, y + 0.20)
  add_rect(cell, layout, LAYER_V4, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
  add_rect(cell, layout, LAYER_M5, x - 0.22, y - 0.22, x + 0.22, y + 0.22)
end

def tile_wl_target(macro_item, row)
  row_index = row.fetch("row_index").to_i
  port = row.fetch("port")
  local_y = TILE_WL_LOCAL_Y_UM.fetch(port).fetch(row_index % 4)
  tile_row = row_index / 4
  tile_pitch_y = macro_item.fetch("tile_height_um").to_f + macro_item.fetch("tile_gap_um").to_f
  [
    macro_item.fetch("row_edge_total_width_um").to_f + TILE_WL_LOCAL_X_UM,
    macro_item.fetch("control_bottom_um").to_f + tile_row * tile_pitch_y + local_y
  ]
end

def remove_legacy_wl_stubs(target, layout, macro_item)
  y0 = macro_item.fetch("control_bottom_um").to_f
  y1 = macro_item.fetch("height_um").to_f - macro_item.fetch("control_top_um").to_f
  physical_rows = macro_item.fetch("physical_rows").to_i
  return 0 if physical_rows <= 0

  predecode = macro_item.fetch("predecode_width_um").to_f
  strip = macro_item.fetch("port_strip_width_um").to_f
  pitch = (y1 - y0) / physical_rows
  stub_h = 0.12
  lane_margin = [0.20, strip / 5.0].min
  deleted = 0
  physical_rows.times do |row|
    y = y0 + row * pitch + pitch / 2.0
    4.times do |idx|
      x0 = predecode + idx * strip + lane_margin
      x1 = predecode + (idx + 1) * strip - lane_margin
      deleted += delete_rect(target, layout, LAYER_M4, x0, y - stub_h, x1, y + stub_h)
    end
  end
  deleted
end

def direct_counts(layout, top)
  counts = Hash.new(0)
  top.each_inst do |inst|
    child = layout.cell(inst.cell_index)
    counts[child.name] += 1 if child && child.name.start_with?("gf180mcu_as_sc_mcu7t3v3__")
  end
  counts
end

def bbox_um(cell, layout)
  box = cell.bbox
  {
    "left_um" => (box.left * layout.dbu).round(6),
    "bottom_um" => (box.bottom * layout.dbu).round(6),
    "right_um" => (box.right * layout.dbu).round(6),
    "top_um" => (box.top * layout.dbu).round(6),
    "width_um" => (box.width * layout.dbu).round(6),
    "height_um" => (box.height * layout.dbu).round(6)
  }
end

def lyrdb_items(path)
  return nil unless File.file?(path)
  doc = REXML::Document.new(File.read(path))
  items = doc.root&.elements&.[]("items")
  return nil unless items
  items.elements.to_a.length
end

def trans_for(row)
  RBA::Trans.new(RBA::Trans::R0, row.fetch("x_dbu"), row.fetch("y_dbu"))
end

raise "missing row-select placement manifest" unless File.file?(ROWSEL_MANIFEST)
raise "missing base GDS manifest" unless File.file?(BASE_GDS_MANIFEST)
FileUtils.mkdir_p(OUT)
rowsel = JSON.parse(File.read(ROWSEL_MANIFEST))
base = JSON.parse(File.read(BASE_GDS_MANIFEST))
base_counts_by_macro = {}
base.fetch("results").each do |item|
  base_counts_by_macro[item.fetch("macro")] = item.fetch("direct_avalon_instance_counts")
end
final_manifest = JSON.parse(File.read(File.join(ROOT, "reports", "final_physical", "MANIFEST.json")))
final_by_macro = final_manifest.to_h { |item| [item.fetch("macro"), item] }
results = []

rowsel.fetch("results").each do |item|
  macro = item.fetch("macro")
  macro_item = final_by_macro.fetch(macro)
  macro_gds = File.join(ROOT, "macros", macro, "layout", "#{macro}.gds")
  csv_path = File.join(ROOT, item.fetch("placement_csv"))
  rows = CSV.read(csv_path, headers: true).map(&:to_h)
  expected_delta = Hash.new(0)
  rows.each { |row| expected_delta[row.fetch("cell")] += 1 }
  expected_total = Hash.new(0)
  base_counts_by_macro.fetch(macro).each { |k, v| expected_total[k] += v.to_i }
  expected_delta.each { |k, v| expected_total[k] += v }

  layout = RBA::Layout.new
  layout.read(macro_gds)
  top = find_cell(layout, macro)
  raise "missing top #{macro}" unless top
  target = find_cell(layout, "#{macro}_array_control_core") || top
  counts_before = direct_counts(layout, target)
  already = expected_total.all? { |k, v| counts_before[k] == v }
  inserted = 0
  route_shapes = 0
  unless already
    base_ok = base_counts_by_macro.fetch(macro).all? { |k, v| counts_before[k] == v.to_i }
    raise "#{macro}: unexpected existing Avalon counts #{counts_before}" unless base_ok
    layout.read(AVALON_GDS)
    rows.each do |row|
      child = find_cell(layout, row.fetch("cell"))
      raise "#{macro}: missing #{row.fetch('cell')} in Avalon GDS" unless child
      row["x_dbu"] = dbu(layout, row.fetch("x_um"))
      row["y_dbu"] = dbu(layout, row.fetch("y_um"))
      target.insert(RBA::CellInstArray.new(child.cell_index, trans_for(row)))
      inserted += 1
    end
  end

  $shape_index = build_shape_index(target, layout, ROUTE_LAYERS)
  legacy_wl_stub_shapes_removed = remove_legacy_wl_stubs(target, layout, macro_item)

  grouped = rows.group_by { |row| row.fetch("original_name") }
  grouped.each_value do |cells|
    by_role = cells.to_h { |row| [row.fetch("role"), row] }
    nand = by_role["nand4"] || by_role["nand3"]
      inv0 = by_role.fetch("buf0")
      inv1 = by_role.fetch("buf1")
      inv2 = by_role.fetch("buf2")
      y = nand.fetch("y_um").to_f
      route_y = y + 1.86
      # Local M1 signal stitching: NAND Y -> INV0 A -> INV1 A -> INV2 A.
      [[nand, inv0, 6.64, 0.49], [inv0, inv1, 1.18, 0.49], [inv1, inv2, 1.18, 0.49]].each do |src, dst, src_dx, dst_dx|
        x0 = src.fetch("x_um").to_f + src_dx
        x1 = dst.fetch("x_um").to_f + dst_dx
      add_rect(target, layout, LAYER_M1, [x0, x1].min, route_y - 0.12, [x0, x1].max, route_y + 0.12)
      route_shapes += 1
    end
    # Tie final INV output to the actual tile WL/RWL M5 landing pin.
    wl_x = inv2.fetch("x_um").to_f + 1.18
    tile_x, wl_y = tile_wl_target(macro_item, nand)
    add_rect(target, layout, LAYER_M1, wl_x - 0.12, [route_y, wl_y].min, wl_x + 0.12, [route_y, wl_y].max)
    add_stack_m1_to_m4(target, layout, wl_x, wl_y)
    add_rect(target, layout, LAYER_M4, [wl_x, tile_x].min, wl_y - 0.16, [wl_x, tile_x].max, wl_y + 0.16)
    add_stack_m4_to_m5(target, layout, tile_x, wl_y)
    route_shapes += 12
  end

    # Stitch local standard-cell rails per port to M2 vertical trunks and into
    # bottom/top control-band M4 power rails.  This gives the row-select rows a
    # physical power path without crossing the M4 WL stubs.
    ports = rows.group_by { |row| row.fetch("port") }
    ports.each_value do |port_rows|
      xs = port_rows.map { |row| row.fetch("x_um").to_f }
      xe = port_rows.map { |row| row.fetch("x_um").to_f + row.fetch("width_um").to_f }
      x0 = xs.min
      x1 = xe.max
      vss_x = x0 + 0.42
      vdd_x = x1 - 0.42
      ys = port_rows.map { |row| row.fetch("y_um").to_f }
      old_y_low = ys.min - 0.30
      old_y_high = ys.max + 4.22
      y_low = ys.min - 0.18
      y_high = ys.max + 4.10
      delete_rect(target, layout, LAYER_M2, vss_x - 0.17, old_y_low, vss_x + 0.17, old_y_high)
      delete_rect(target, layout, LAYER_M2, vdd_x - 0.17, old_y_low, vdd_x + 0.17, old_y_high)
      add_rect(target, layout, LAYER_M2, vss_x - 0.17, y_low, vss_x + 0.17, y_high)
      add_rect(target, layout, LAYER_M2, vdd_x - 0.17, y_low, vdd_x + 0.17, y_high)
      route_shapes += 2
      port_rows.each do |row|
        y = row.fetch("y_um").to_f
        # Older repair merged full-width M1 row power rails.  With 4.325um row
        # pitch and 3.92um cells, those wide rails can overlap the next row's
        # opposite supply.  Keep only local M1 landing pads at the M2 trunks;
        # horizontal power continuity is provided by the abutted stdcell rails.
        delete_rect(target, layout, LAYER_M1, x0, y - 0.30, x1, y + 0.30)
        delete_rect(target, layout, LAYER_M1, x0, y + 3.62, x1, y + 4.22)
        add_rect(target, layout, LAYER_M1, vss_x - 0.18, y - 0.18, vss_x + 0.18, y + 0.18)
        add_rect(target, layout, LAYER_M1, vdd_x - 0.18, y + 3.74, vdd_x + 0.18, y + 4.10)
        add_rect(target, layout, LAYER_V1, vss_x - 0.11, y - 0.11, vss_x + 0.11, y + 0.11)
        add_rect(target, layout, LAYER_V1, vdd_x - 0.11, y + 3.81, vdd_x + 0.11, y + 4.03)
        route_shapes += 4
      end
      [vss_x, vdd_x].each_with_index do |x, idx|
        y = idx.zero? ? 0.9 : macro_item.fetch("height_um").to_f - 0.9
        delete_rect(target, layout, LAYER_M2, x - 0.17, [y, old_y_low].min, x + 0.17, [y, old_y_high].max)
        add_rect(target, layout, LAYER_M2, x - 0.17, [y, y_low].min, x + 0.17, [y, y_high].max)
        add_rect(target, layout, LAYER_V2, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
        add_rect(target, layout, LAYER_M3, x - 0.18, y - 0.18, x + 0.18, y + 0.18)
        add_rect(target, layout, LAYER_V3, x - 0.11, y - 0.11, x + 0.11, y + 0.11)
        add_rect(target, layout, LAYER_M4, x - 0.20, y - 0.20, x + 0.20, y + 0.20)
        route_shapes += 5
      end
  end

  final_counts = direct_counts(layout, target)
  bad = expected_total.select { |k, v| final_counts[k] != v }
  bbox = bbox_um(target, layout)
  fp = (bbox.fetch("width_um") - macro_item.fetch("width_um").to_f).abs <= 0.001 &&
       (bbox.fetch("height_um") - macro_item.fetch("height_um").to_f).abs <= 0.001 &&
       bbox.fetch("left_um").abs <= 0.001 &&
       bbox.fetch("bottom_um").abs <= 0.001
  status = bad.empty? && fp ? "PASS" : "FAIL"
  if status == "PASS"
    tmp = "#{macro_gds}.tmp_row_select_merge.gds"
    layout.write(tmp)
    FileUtils.mv(tmp, macro_gds)
  end
  results << {
    "macro" => macro,
    "status" => status,
    "already_integrated" => already,
    "inserted_stdcells" => inserted,
    "row_select_stdcells" => expected_delta.values.sum,
    "route_shapes_added" => route_shapes,
    "legacy_wl_stub_shapes_removed" => legacy_wl_stub_shapes_removed,
    "wl_route_policy" => "row-select INV outputs route directly to real 4x4 tile WL/RWL metal5 landing pins; no abstract M4 row-center stubs",
    "expected_delta_counts" => expected_delta.sort.to_h,
    "direct_avalon_instance_counts" => final_counts.sort.to_h,
    "footprint_unchanged" => fp,
    "bbox_um" => bbox,
    "gds" => rel(macro_gds),
    "detail" => bad.empty? ? [] : ["count mismatch #{bad.inspect}"]
  }
end

status = results.all? { |item| item.fetch("status") == "PASS" } ? "PASS" : "FAIL"
manifest = {
  "package" => "gf180mcu-3v3-12t-2r2w-sram-macro",
  "status" => status,
  "scope" => "physically merged row-select/WL-buffer Avalon stdcell expansion into macro GDS",
  "row_select_manifest" => rel(ROWSEL_MANIFEST),
  "base_gds_manifest" => rel(BASE_GDS_MANIFEST),
  "results" => results
}
File.write(File.join(OUT, "MANIFEST.json"), JSON.pretty_generate(manifest) + "\n")
lines = [
  "# Row-Select Stdcell GDS Merge",
  "",
  "Row-select/WL-buffer functions are physically implemented with Avalon NAND/INV stdcells inside the existing row-edge strips.",
  "This closes physical row-select stdcell presence and routes WL-buffer outputs directly to the real 4x4 tile WL/RWL metal5 landing pins. Upstream control/predecode routing is handled by `route_gf180mcu_3v3_12t_2r2w_sram_control_signals.rb`.",
  "",
  "| Macro | Status | Row-select stdcells | Newly inserted this run | Route shapes | Footprint |",
  "| --- | --- | ---: | ---: | ---: | --- |"
]
results.each do |item|
  lines << "| `#{item.fetch('macro')}` | `#{item.fetch('status')}` | #{item.fetch('row_select_stdcells')} | #{item.fetch('inserted_stdcells')} | #{item.fetch('route_shapes_added')} | `#{item.fetch('footprint_unchanged')}` |"
end
smoke_report = File.join(OUT, "gf180mcu_3v3_12t_2r2w_sram_512x8", "main_drc.lyrdb")
smoke_items = lyrdb_items(smoke_report)
unless smoke_items.nil?
  lines += [
    "",
    "Smoke DRC:",
    "",
    "- `gf180mcu_3v3_12t_2r2w_sram_512x8`: GF180 KLayout `main.drc` #{smoke_items.zero? ? 'PASS' : 'FAIL'}, `#{smoke_items}` violations, report `#{rel(smoke_report)}`."
  ]
end
File.write(File.join(OUT, "README.md"), lines.join("\n") + "\n")
puts "GF180MCU 12T SRAM row-select GDS merge: #{status}"
puts File.join(OUT, "MANIFEST.json")
exit(status == "PASS" ? 0 : 1)
