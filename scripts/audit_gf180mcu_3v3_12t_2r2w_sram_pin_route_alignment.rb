#!/usr/bin/env ruby
# Audit that generated physical route geometry actually lands on declared pins.

require "csv"
require "json"

ROOT = File.expand_path("..", __dir__)

FINAL_MANIFEST = File.join(ROOT, "reports", "final_physical", "MANIFEST.json")
ROWSEL_MANIFEST = File.join(ROOT, "reports", "stdcell_row_select_placement", "MANIFEST.json")
COLUMN_MANIFEST = File.join(ROOT, "reports", "column_periphery_integration", "MANIFEST.json")
COLUMN_GDS_MANIFEST = File.join(ROOT, "reports", "column_periphery_gds_merge", "MANIFEST.json")
WRITE_PINS = File.join(ROOT, "reports", "periphery_block_leaves", "detronyx_12t_write_driver_rc1", "abstract", "detronyx_12t_write_driver_rc1.pins.json")
READ_PINS = File.join(ROOT, "reports", "periphery_block_leaves", "detronyx_12t_precharge_sense_rc1", "abstract", "detronyx_12t_precharge_sense_rc1.pins.json")

LAYER_M1 = [34, 0].freeze
LAYER_M3 = [42, 0].freeze
LAYER_M4 = [46, 0].freeze
LAYER_M5 = [81, 0].freeze
DUMMY_ROUTE_LAYERS = [[30, 0], [34, 4], [36, 4], [42, 4], [46, 4], [81, 4]].freeze
UNITS_PER_UM = 200.0

TILE_WL_LOCAL_X_UM = 0.150
TILE_WL_LOCAL_Y_UM = {
  "w0" => [0.450, 4.310, 8.170, 12.030],
  "w1" => [1.650, 5.510, 9.370, 13.230],
  "r0" => [1.000, 4.860, 8.720, 12.580],
  "r1" => [2.350, 6.210, 10.070, 13.930]
}.freeze

def rel(path)
  path.sub("#{ROOT}/", "")
end

def load_json(path)
  JSON.parse(File.read(path))
end

def read_csv(path)
  CSV.read(path, headers: true).map(&:to_h)
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

def layer(layout, pair)
  layout.layer(pair[0], pair[1])
end

def dbu(layout, value_um)
  (value_um.to_f / layout.dbu).round
end

def point_covered?(cell, layout, pair, x_um, y_um)
  x = dbu(layout, x_um)
  y = dbu(layout, y_um)
  layer_index = layout.layer(pair[0], pair[1])
  found = false
  cell.shapes(layer_index).each do |shape|
    box = shape.bbox
    if box.left <= x && x <= box.right && box.bottom <= y && y <= box.top
      found = true
      break
    end
  end
  found
end

def count_shapes(cell, layout, pair)
  count = 0
  cell.shapes(layer(layout, pair)).each { |_shape| count += 1 }
  count
end

def leaf_pins(path)
  data = load_json(path)
  pins = data.is_a?(Array) ? data : data.fetch("pins")
  pins.to_h do |pin|
    x = (pin.fetch("xlo").to_f + pin.fetch("xhi").to_f) / (2.0 * UNITS_PER_UM)
    y = (pin.fetch("ylo").to_f + pin.fetch("yhi").to_f) / (2.0 * UNITS_PER_UM)
    [pin.fetch("name"), [x, y]]
  end
end

def macro_pins(path)
  load_json(path).to_h do |pin|
    rect = pin.fetch("rect_um")
    x = (rect[0].to_f + rect[2].to_f) / 2.0
    y = (rect[1].to_f + rect[3].to_f) / 2.0
    [pin.fetch("name"), [x, y, pin]]
  end
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

def legacy_stub_like_count(cell, layout, macro_item)
  y0 = (macro_item.fetch("control_bottom_um").to_f * UNITS_PER_UM).round
  y1 = ((macro_item.fetch("height_um").to_f - macro_item.fetch("control_top_um").to_f) * UNITS_PER_UM).round
  physical_rows = macro_item.fetch("physical_rows").to_i
  return 0 if physical_rows <= 0

  pitch = (y1 - y0) / physical_rows
  stub_h = (0.12 * UNITS_PER_UM).round
  y_bands = {}
  physical_rows.times do |row|
    y = y0 + row * pitch + pitch / 2
    y_bands[[y - stub_h, y + stub_h]] = true
  end

  count = 0
  cell.shapes(layer(layout, LAYER_M4)).each do |shape|
    box = shape.bbox
    next unless y_bands.key?([box.bottom, box.top])
    next unless (box.right - box.left) >= dbu(layout, 1.0)
    count += 1
  end
  count
end

def add_missing(missing, counters, kind, macro, name, layer_name, x, y)
  counters["missing_points"] += 1
  missing << {
    "kind" => kind,
    "macro" => macro,
    "name" => name,
    "layer" => layer_name,
    "x_um" => x.round(6),
    "y_um" => y.round(6)
  } if missing.length < 80
end

def check_point(cell, layout, pair, layer_name, missing, counters, kind, macro, name, x, y)
  counters["checked_points"] += 1
  return true if point_covered?(cell, layout, pair, x, y)
  add_missing(missing, counters, kind, macro, name, layer_name, x, y)
  false
end

def audit_row_select(macro, layout, core, macro_item, rowsel_item)
  rows = read_csv(File.join(ROOT, rowsel_item.fetch("placement_csv")))
  missing = []
  counters = {"checked_points" => 0, "missing_points" => 0}
  rows.group_by { |row| row.fetch("original_name") }.each do |original_name, cells|
    by_role = cells.to_h { |row| [row.fetch("role"), row] }
    nand = by_role["nand4"] || by_role["nand3"]
    inv2 = by_role.fetch("buf2")
    route_y = nand.fetch("y_um").to_f + 1.86
    wl_x = inv2.fetch("x_um").to_f + 1.18
    tile_x, wl_y = tile_wl_target(macro_item, nand)
    mid_x = (wl_x + tile_x) / 2.0

    [
      [LAYER_M1, "M1", wl_x, route_y, "final_inv_output_m1"],
      [LAYER_M1, "M1", wl_x, wl_y, "wl_drop_m1"],
      [LAYER_M4, "M4", wl_x, wl_y, "wl_drop_m4_stack"],
      [LAYER_M4, "M4", mid_x, wl_y, "wl_horizontal_m4"],
      [LAYER_M4, "M4", tile_x, wl_y, "tile_wl_m4_stack"],
      [LAYER_M5, "M5", tile_x, wl_y, "tile_wl_m5_landing"]
    ].each do |pair, layer_name, x, y, point_name|
      check_point(core, layout, pair, layer_name, missing, counters, "row_select_pin_route_alignment", macro, "#{original_name}:#{point_name}", x, y)
    end
  end

  {
    "checked_points" => counters.fetch("checked_points"),
    "missing_points" => counters.fetch("missing_points"),
    "missing_examples" => missing
  }
end

def audit_column_periphery(macro, layout, route_cell, column_item)
  placement = read_csv(File.join(ROOT, column_item.fetch("placement_csv")))
  routes = read_csv(File.join(ROOT, column_item.fetch("routes_csv")))
  pins = macro_pins(File.join(ROOT, column_item.fetch("pins_json")))
  leaf_by_block = {
    "write_driver" => leaf_pins(WRITE_PINS),
    "precharge_sense" => leaf_pins(READ_PINS)
  }
  inst_by_name = placement.to_h { |row| [row.fetch("name"), row] }
  missing = []
  counters = {"checked_points" => 0, "missing_points" => 0}

  routes.each do |route|
    inst = inst_by_name.fetch(route.fetch("inst"))
    local = leaf_by_block.fetch(inst.fetch("block"))
    ix = inst.fetch("x_um").to_f
    iy = inst.fetch("y_um").to_f
    mx, my, = pins.fetch(route.fetch("macro_pin"))

    pin_name, source_layer, macro_layer, endpoint = case route.fetch("kind")
    when "read_dout"
      ["dout", LAYER_M5, LAYER_M5, [mx, my]]
    when "write_din"
      ["din", LAYER_M5, LAYER_M5, [mx, my]]
    when "write_enable"
      ["wen", LAYER_M4, LAYER_M4, [mx, my]]
    when "read_enable"
      ["ren", LAYER_M4, LAYER_M4, [mx, my]]
    when "read_precharge_landing"
      ["pchgb", LAYER_M4, LAYER_M4, [mx, my]]
    when "read_rbl_landing"
      ["rbl0", LAYER_M4, nil, nil]
    when "write_wbl_landing"
      ["wbl0", LAYER_M4, nil, nil]
    when "write_wbr_landing"
      ["wbr0", LAYER_M4, nil, nil]
    else
      raise "#{macro}: unsupported route kind #{route.fetch('kind')}"
    end

    lx, ly = local.fetch(pin_name)
    sx = ix + lx
    sy = iy + ly
    check_point(route_cell, layout, LAYER_M3, "M3", missing, counters, "column_pin_route_alignment", macro, "#{route.fetch('inst')}:#{pin_name}:source_m3", sx, sy)
    check_point(route_cell, layout, source_layer, source_layer == LAYER_M5 ? "M5" : "M4", missing, counters, "column_pin_route_alignment", macro, "#{route.fetch('inst')}:#{pin_name}:source_route", sx, sy)

    if endpoint && macro_layer
      check_point(route_cell, layout, macro_layer, macro_layer == LAYER_M5 ? "M5" : "M4", missing, counters, "column_pin_route_alignment", macro, "#{route.fetch('macro_pin')}:macro_route", endpoint[0], endpoint[1])
    end
  end

  {
    "checked_points" => counters.fetch("checked_points"),
    "missing_points" => counters.fetch("missing_points"),
    "missing_examples" => missing
  }
end

final_by_macro = load_json(FINAL_MANIFEST).to_h { |item| [item.fetch("macro"), item] }
rowsel_by_macro = load_json(ROWSEL_MANIFEST).fetch("results").to_h { |item| [item.fetch("macro"), item] }
column_by_macro = load_json(COLUMN_MANIFEST).fetch("results").to_h { |item| [item.fetch("macro"), item] }
column_gds = load_json(COLUMN_GDS_MANIFEST)

results = []
column_gds.fetch("results").each do |gds_item|
  macro = gds_item.fetch("macro")
  layout = RBA::Layout.new
  layout.read(File.join(ROOT, gds_item.fetch("gds")))
  core = find_cell(layout, "#{macro}_array_control_core")
  route_cell = find_cell(layout, "#{macro}_column_periphery_routes")
  raise "#{macro}: missing array_control_core" unless core
  raise "#{macro}: missing column_periphery_routes" unless route_cell

  dummy_shapes = DUMMY_ROUTE_LAYERS.to_h do |pair|
    [pair.join("/"), count_shapes(route_cell, layout, pair)]
  end
  row_audit = audit_row_select(macro, layout, core, final_by_macro.fetch(macro), rowsel_by_macro.fetch(macro))
  column_audit = audit_column_periphery(macro, layout, route_cell, column_by_macro.fetch(macro))
  legacy_stubs = legacy_stub_like_count(core, layout, final_by_macro.fetch(macro))
  dummy_total = dummy_shapes.values.sum
  route_layer_counts = {
    "layout_dbu" => layout.dbu,
    "core_m1" => count_shapes(core, layout, LAYER_M1),
    "core_m4" => count_shapes(core, layout, LAYER_M4),
    "core_m5" => count_shapes(core, layout, LAYER_M5),
    "column_m3" => count_shapes(route_cell, layout, LAYER_M3),
    "column_m4" => count_shapes(route_cell, layout, LAYER_M4),
    "column_m5" => count_shapes(route_cell, layout, LAYER_M5)
  }
  status = dummy_total.zero? && legacy_stubs.zero? &&
           row_audit.fetch("missing_points").zero? &&
           column_audit.fetch("missing_points").zero? ? "PASS" : "FAIL"

  results << {
    "macro" => macro,
    "status" => status,
    "gds" => gds_item.fetch("gds"),
    "dummy_route_layer_shapes" => dummy_shapes,
    "dummy_route_layer_total" => dummy_total,
    "route_layer_counts" => route_layer_counts,
    "legacy_m4_wl_stub_like_shapes" => legacy_stubs,
    "row_select" => row_audit,
    "column_periphery" => column_audit
  }
end

status = results.all? { |item| item.fetch("status") == "PASS" } ? "PASS" : "FAIL"
report = {
  "package" => "gf180mcu-3v3-12t-2r2w-sram-macro",
  "status" => status,
  "scope" => "KLayout GDS audit for pin-to-route coincidence, no dummy route-cell fill, and no legacy M4 WL stubs",
  "results" => results
}

if $out
  File.write($out, JSON.pretty_generate(report) + "\n")
end
puts JSON.pretty_generate(report)
exit(status == "PASS" ? 0 : 1)
