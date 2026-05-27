#!/usr/bin/env ruby
# Wrap macro GDS tops with pitch-aware column periphery leaf instances and routes.

require "csv"
require "fileutils"
require "json"
require "rexml/document"

ROOT = File.expand_path("..", __dir__)
PLAN = File.join(ROOT, "reports", "column_periphery_integration", "MANIFEST.json")
OUT = File.join(ROOT, "reports", "column_periphery_gds_merge")

LAYER_M3 = [42, 0].freeze
LAYER_V3 = [40, 0].freeze
LAYER_M4 = [46, 0].freeze
LAYER_V4 = [41, 0].freeze
LAYER_M5 = [81, 0].freeze
LAYER_POLY = [30, 0].freeze
FILL_LAYERS = [[34, 4], [36, 4], [42, 4], [46, 4], [81, 4]].freeze
GRID_UM = 0.005
WIRE_W = 0.36
PIN_W = 0.64
VIA_W = 0.22
POWER_RAIL_W = 1.20
UNITS_PER_UM = 200.0

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

def snap_um(value)
  (value.to_f / GRID_UM).round * GRID_UM
end

def dbu(layout, value_um)
  (snap_um(value_um) / layout.dbu).round
end

def layer(layout, pair)
  layout.layer(pair[0], pair[1])
end

def box_um(layout, x0, y0, x1, y1)
  RBA::Box.new(dbu(layout, x0), dbu(layout, y0), dbu(layout, x1), dbu(layout, y1))
end

def add_rect(cell, layout, pair, x0, y0, x1, y1)
  return 0 if x1 <= x0 || y1 <= y0
  cell.shapes(layer(layout, pair)).insert(box_um(layout, x0, y0, x1, y1))
  1
end

def add_square(cell, layout, pair, x, y, size)
  half = size / 2.0
  add_rect(cell, layout, pair, x - half, y - half, x + half, y + half)
end

def add_stack_m3_m5(cell, layout, x, y)
  shapes = 0
  shapes += add_square(cell, layout, LAYER_M3, x, y, PIN_W)
  shapes += add_square(cell, layout, LAYER_V3, x, y, VIA_W)
  shapes += add_square(cell, layout, LAYER_M4, x, y, PIN_W)
  shapes += add_square(cell, layout, LAYER_V4, x, y, VIA_W)
  shapes += add_square(cell, layout, LAYER_M5, x, y, PIN_W)
  shapes
end

def add_stack_m3_m4(cell, layout, x, y)
  shapes = 0
  shapes += add_square(cell, layout, LAYER_M3, x, y, PIN_W)
  shapes += add_square(cell, layout, LAYER_V3, x, y, VIA_W)
  shapes += add_square(cell, layout, LAYER_M4, x, y, PIN_W)
  shapes
end

def add_m5_wire(cell, layout, x0, y0, x1, y1, width = WIRE_W)
  if (x1 - x0).abs >= (y1 - y0).abs
    add_rect(cell, layout, LAYER_M5, [x0, x1].min, y0 - width / 2.0, [x0, x1].max, y0 + width / 2.0)
  else
    add_rect(cell, layout, LAYER_M5, x0 - width / 2.0, [y0, y1].min, x0 + width / 2.0, [y0, y1].max)
  end
end

def add_m4_wire(cell, layout, x0, y0, x1, y1, width = WIRE_W)
  if (x1 - x0).abs >= (y1 - y0).abs
    add_rect(cell, layout, LAYER_M4, [x0, x1].min, y0 - width / 2.0, [x0, x1].max, y0 + width / 2.0)
  else
    add_rect(cell, layout, LAYER_M4, x0 - width / 2.0, [y0, y1].min, x0 + width / 2.0, [y0, y1].max)
  end
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

def read_csv(path)
  CSV.read(path, headers: true).map(&:to_h)
end

def leaf_pins(path)
  data = JSON.parse(File.read(path))
  pins = data.is_a?(Array) ? data : data.fetch("pins")
  pins.to_h do |pin|
    x = (pin.fetch("xlo").to_f + pin.fetch("xhi").to_f) / (2.0 * UNITS_PER_UM)
    y = (pin.fetch("ylo").to_f + pin.fetch("yhi").to_f) / (2.0 * UNITS_PER_UM)
    [pin.fetch("name"), [x, y]]
  end
end

def macro_pins(path)
  JSON.parse(File.read(path)).to_h do |pin|
    rect = pin.fetch("rect_um")
    x = (rect[0].to_f + rect[2].to_f) / 2.0
    y = (rect[1].to_f + rect[3].to_f) / 2.0
    [pin.fetch("name"), [x, y, pin]]
  end
end

def direct_child_counts(layout, top)
  counts = Hash.new(0)
  top.each_inst do |inst|
    child = layout.cell(inst.cell_index)
    counts[child.name] += 1 if child
  end
  counts
end

def clear_cell_shapes(cell, layout)
  ([LAYER_M3, LAYER_V3, LAYER_M4, LAYER_V4, LAYER_M5] + FILL_LAYERS + [LAYER_POLY]).each do |pair|
    cell.shapes(layer(layout, pair)).clear
  end
end

def boxes_overlap?(a, b)
  a.left < b.right && b.left < a.right && a.bottom < b.top && b.bottom < a.top
end

def delete_fill_shapes_in_keepouts(cell, layout, pair, keepouts)
  return 0 if keepouts.empty?
  shapes = cell.shapes(layer(layout, pair))
  victims = []
  shapes.each do |shape|
    bbox = shape.bbox
    victims << shape if keepouts.any? { |keepout| boxes_overlap?(bbox, keepout) }
  end
  victims.each(&:delete)
  victims.length
end

def core_density_keepouts(layout, instances, core_y, core_bbox)
  margin = 0.60
  left = core_bbox.fetch("left_um").to_f
  bottom = core_bbox.fetch("bottom_um").to_f
  right = core_bbox.fetch("right_um").to_f
  top = core_bbox.fetch("top_um").to_f
  keepouts = []

  instances.each do |row|
    x0 = row.fetch("x_um").to_f - margin
    y0 = row.fetch("y_um").to_f - core_y - margin
    x1 = row.fetch("x_um").to_f + row.fetch("width_um").to_f + margin
    y1 = row.fetch("y_um").to_f + row.fetch("height_um").to_f - core_y + margin
    x0 = [x0, left].max
    y0 = [y0, bottom].max
    x1 = [x1, right].min
    y1 = [y1, top].min
    next if x1 <= x0 || y1 <= y0
    keepouts << box_um(layout, x0, y0, x1, y1)
  end

  keepouts
end

def clear_core_density_fill(cell, layout, instances, core_y, core_bbox)
  # The final-physical GDS source intentionally carries coarse density/fill
  # geometry in the top/bottom control corridors.  When column periphery is
  # packed into those corridors, clear only local keepouts under placed devices;
  # preserving the rest avoids regressing local density.
  keepouts = core_density_keepouts(layout, instances, core_y, core_bbox)
  deleted = 0
  (FILL_LAYERS + [LAYER_POLY]).each do |pair|
    deleted += delete_fill_shapes_in_keepouts(cell, layout, pair, keepouts)
  end
  deleted
end

def wrapper_instance_keepouts(layout, instances)
  margin = 0.60
  instances.map do |row|
    box_um(
      layout,
      row.fetch("x_um").to_f - margin,
      row.fetch("y_um").to_f - margin,
      row.fetch("x_um").to_f + row.fetch("width_um").to_f + margin,
      row.fetch("y_um").to_f + row.fetch("height_um").to_f + margin
    )
  end
end

def add_fill_grid_shapes(cell, layout, pair, x0, y0, x1, y1, pitch, fill, keepouts = [])
  return 0 if x1 <= x0 || y1 <= y0
  count = 0
  shapes = cell.shapes(layer(layout, pair))
  y = y0
  while y + fill <= y1
    x = x0
    while x + fill <= x1
      candidate = box_um(layout, x, y, x + fill, y + fill)
      unless keepouts.any? { |keepout| boxes_overlap?(candidate, keepout) }
        shapes.insert(candidate)
        count += 1
      end
      x += pitch
    end
    y += pitch
  end
  count
end

def add_wrapper_density_fill(cell, layout, item, instances)
  pitch = 14.0
  fill = 8.0
  margin = 1.0
  new_w = item.fetch("new_width_um").to_f
  new_h = item.fetch("new_height_um").to_f
  old_h = item.fetch("old_height_um").to_f
  core_y = item.fetch("core_y_offset_um").to_f
  row_edge_w = item.fetch("row_edge_total_width_um", 0.0).to_f
  control_bottom = item.fetch("core_control_bottom_um", 0.0).to_f
  control_top = item.fetch("core_control_top_um", 0.0).to_f
  keepouts = wrapper_instance_keepouts(layout, instances)
  shapes = 0

  FILL_LAYERS.each do |pair|
    shapes += add_fill_grid_shapes(cell, layout, pair, margin, margin, new_w - margin, new_h - margin, pitch, fill, keepouts)
  end

  poly_fill = 12.0
  poly_windows = [
    [margin, margin, [margin, row_edge_w - margin].max, new_h - margin],
    [row_edge_w + margin, margin, new_w - margin, core_y + [control_bottom - margin, margin].max],
    [row_edge_w + margin, core_y + old_h - control_top + margin, new_w - margin, new_h - margin]
  ]
  poly_windows.each do |x0, y0, x1, y1|
    shapes += add_fill_grid_shapes(cell, layout, LAYER_POLY, x0, y0, x1, y1, pitch, poly_fill, keepouts)
  end

  shapes
end

def clear_top_instances(top)
  top.each_inst { |inst| inst.delete }
end

def delete_cell_by_name(layout, name)
  cell = find_cell(layout, name)
  return false unless cell
  layout.delete_cell(cell.cell_index)
  true
end

def lyrdb_items(path)
  return nil unless File.file?(path)
  doc = REXML::Document.new(File.read(path))
  items = doc.root&.elements&.[]("items")
  return nil unless items
  items.elements.to_a.length
end

def remove_old_wrapper_cells(layout, macro)
  ["#{macro}_column_periphery_routes", "#{macro}_array_control_core"].each do |name|
    cell = find_cell(layout, name)
    next unless cell
    # These cells are not deleted because KLayout object deletion varies by
    # version; recreating from a clean macro top avoids partial reuse.
  end
end

raise "missing column periphery plan: #{PLAN}" unless File.file?(PLAN)

FileUtils.mkdir_p(OUT)
plan = JSON.parse(File.read(PLAN))
write_pins = leaf_pins(File.join(ROOT, "reports", "periphery_block_leaves", "detronyx_12t_write_driver_rc1", "abstract", "detronyx_12t_write_driver_rc1.pins.json"))
read_pins = leaf_pins(File.join(ROOT, "reports", "periphery_block_leaves", "detronyx_12t_precharge_sense_rc1", "abstract", "detronyx_12t_precharge_sense_rc1.pins.json"))
leaf_pin_by_block = {
  "write_driver" => write_pins,
  "precharge_sense" => read_pins
}
results = []

plan.fetch("results").each do |item|
  macro = item.fetch("macro")
  macro_gds = File.join(ROOT, item.fetch("gds"))
  placement_csv = File.join(ROOT, item.fetch("placement_csv"))
  routes_csv = File.join(ROOT, item.fetch("routes_csv"))
  pins_json = File.join(ROOT, item.fetch("pins_json"))
  raise "missing macro GDS #{macro_gds}" unless File.file?(macro_gds)
  raise "missing placement CSV #{placement_csv}" unless File.file?(placement_csv)

  layout = RBA::Layout.new
  layout.read(macro_gds)
  old_top = find_cell(layout, macro)
  raise "#{macro}: top cell not found" unless old_top
  core = find_cell(layout, "#{macro}_array_control_core")
  if core
    top = old_top
    old_bbox = bbox_um(core, layout)
    clear_top_instances(top)
  else
    old_bbox = bbox_um(old_top, layout)
    old_top.name = "#{macro}_array_control_core"
    core = old_top
    top = layout.create_cell(macro)
  end

  core_y = item.fetch("core_y_offset_um").to_f
  control_bottom = item.fetch("core_control_bottom_um", 0.0).to_f
  control_top = item.fetch("core_control_top_um", 0.0).to_f
  instances = read_csv(placement_csv)
  cleared_fill_shapes = clear_core_density_fill(core, layout, instances, core_y, old_bbox)
  top.insert(RBA::CellInstArray.new(core.cell_index, RBA::Trans.new(RBA::Trans::R0, dbu(layout, 0), dbu(layout, core_y))))

  instances.map { |row| row.fetch("cell") }.uniq.each do |cell_name|
    delete_cell_by_name(layout, cell_name)
  end
  gds_by_path = instances.map { |row| File.join(ROOT, row.fetch("gds")) }.uniq
  gds_by_path.each do |path|
    raise "missing leaf GDS #{path}" unless File.file?(path)
    layout.read(path)
  end

  inst_by_name = {}
  instances.each do |row|
    child = find_cell(layout, row.fetch("cell"))
    raise "#{macro}: missing leaf cell #{row.fetch('cell')}" unless child
    x = dbu(layout, row.fetch("x_um"))
    y = dbu(layout, row.fetch("y_um"))
    top.insert(RBA::CellInstArray.new(child.cell_index, RBA::Trans.new(RBA::Trans::R0, x, y)))
    inst_by_name[row.fetch("name")] = row
  end

  route_cell = find_cell(layout, "#{macro}_column_periphery_routes") || layout.create_cell("#{macro}_column_periphery_routes")
  clear_cell_shapes(route_cell, layout)
  pins = macro_pins(pins_json)
  route_rows = read_csv(routes_csv)
  route_shapes = 0

  route_rows.each do |route|
    inst = inst_by_name.fetch(route.fetch("inst"))
    block = inst.fetch("block")
    local = leaf_pin_by_block.fetch(block)
    ix = inst.fetch("x_um").to_f
    iy = inst.fetch("y_um").to_f
    macro_pin = pins.fetch(route.fetch("macro_pin"))
    mx = macro_pin[0]
    my = macro_pin[1]
    kind = route.fetch("kind")

    case kind
    when "read_dout"
      lx, ly = local.fetch("dout")
      sx = ix + lx
      sy = iy + ly
      trunk_y = [my + 2.0, sy - 1.2].max
      route_shapes += add_stack_m3_m5(route_cell, layout, sx, sy)
      route_shapes += add_square(route_cell, layout, LAYER_M5, mx, my, PIN_W)
      route_shapes += add_m5_wire(route_cell, layout, sx, sy, sx, trunk_y)
      route_shapes += add_m5_wire(route_cell, layout, sx, trunk_y, mx, trunk_y)
      route_shapes += add_m5_wire(route_cell, layout, mx, trunk_y, mx, my)
    when "write_din"
      lx, ly = local.fetch("din")
      sx = ix + lx
      sy = iy + ly
      route_shapes += add_stack_m3_m5(route_cell, layout, sx, sy)
      route_shapes += add_square(route_cell, layout, LAYER_M5, mx, my, PIN_W)
      route_shapes += add_m5_wire(route_cell, layout, sx, sy, mx, sy)
      route_shapes += add_m5_wire(route_cell, layout, mx, sy, mx, my)
    when "write_enable"
      lx, ly = local.fetch("wen")
      sx = ix + lx
      sy = iy + ly
      route_shapes += add_stack_m3_m4(route_cell, layout, sx, sy)
      route_shapes += add_square(route_cell, layout, LAYER_M4, mx, my, PIN_W)
      route_shapes += add_m4_wire(route_cell, layout, sx, sy, sx, my)
      route_shapes += add_m4_wire(route_cell, layout, sx, my, mx, my)
    when "read_enable"
      lx, ly = local.fetch("ren")
      sx = ix + lx
      sy = iy + ly
      route_shapes += add_stack_m3_m4(route_cell, layout, sx, sy)
      route_shapes += add_square(route_cell, layout, LAYER_M4, mx, my, PIN_W)
      route_shapes += add_m4_wire(route_cell, layout, sx, sy, sx, my)
      route_shapes += add_m4_wire(route_cell, layout, sx, my, mx, my)
    when "read_precharge_landing"
      lx, ly = local.fetch("pchgb")
      sx = ix + lx
      sy = iy + ly
      route_shapes += add_stack_m3_m4(route_cell, layout, sx, sy)
      route_shapes += add_square(route_cell, layout, LAYER_M4, mx, my, PIN_W)
      route_shapes += add_m4_wire(route_cell, layout, sx, sy, sx, my)
      route_shapes += add_m4_wire(route_cell, layout, sx, my, mx, my)
    when "read_rbl_landing"
      lx, ly = local.fetch("rbl0")
      sx = ix + lx
      sy = iy + ly
      route_shapes += add_stack_m3_m4(route_cell, layout, sx, sy)
      route_shapes += add_m4_wire(route_cell, layout, sx, sy, sx, core_y + [control_bottom - 0.6, 0.6].max)
    when "write_wbl_landing", "write_wbr_landing"
      pin_name = kind == "write_wbl_landing" ? "wbl0" : "wbr0"
      lx, ly = local.fetch(pin_name)
      sx = ix + lx
      sy = iy + ly
      array_top = core_y + item.fetch("old_height_um").to_f - control_top
      route_shapes += add_stack_m3_m4(route_cell, layout, sx, sy)
      route_shapes += add_m4_wire(route_cell, layout, sx, sy, sx, array_top + 0.6)
    else
      raise "#{macro}: unsupported route kind #{kind}"
    end
  end

  # Global top/bottom M5 power rails for the expanded wrapper.  Do not create
  # long M5 drops from every periphery leaf power pin here: those drops cross
  # the column data/control routing and collapse VDD/VSS into one M5 region.
  # Dedicated row-local power stitching is left to the PDN route stage.
  new_w = item.fetch("new_width_um").to_f
  new_h = item.fetch("new_height_um").to_f
  route_shapes += add_rect(route_cell, layout, LAYER_M5, 0, 0, new_w, POWER_RAIL_W)
  route_shapes += add_rect(route_cell, layout, LAYER_M5, 0, new_h - POWER_RAIL_W, new_w, new_h)
  # Route cells must contain only intentional signal/power route geometry.
  # Manual dummy fill/poly was too easy to confuse with real connectivity in
  # KLayout review and extraction audits, so density closure is a separate
  # signoff/fill step instead of part of the route wrapper.
  density_fill_shapes = 0

  top.insert(RBA::CellInstArray.new(route_cell.cell_index, RBA::Trans.new(RBA::Trans::R0, 0, 0)))
  bbox = bbox_um(top, layout)
  counts = direct_child_counts(layout, top)
  expected_h = item.fetch("new_height_um").to_f
  status = "PASS"
  detail = []
  if (bbox.fetch("width_um") - item.fetch("new_width_um").to_f).abs > 0.001 ||
     (bbox.fetch("height_um") - expected_h).abs > 0.001 ||
     bbox.fetch("left_um").abs > 0.001 ||
     bbox.fetch("bottom_um").abs > 0.001
    status = "FAIL"
    detail << "bbox mismatch: #{bbox}, expected width=#{item.fetch('new_width_um')} height=#{expected_h}"
  end
  if route_shapes <= 0
    status = "FAIL"
    detail << "no route shapes emitted"
  end

  if status == "PASS"
    tmp = "#{macro_gds}.tmp_column_periphery.gds"
    layout.write(tmp)
    FileUtils.mv(tmp, macro_gds)
  end

  out_dir = File.join(OUT, macro)
  FileUtils.mkdir_p(out_dir)
  results << {
    "macro" => macro,
    "status" => status,
    "gds" => rel(macro_gds),
    "old_core_cell" => core.name,
    "route_cell" => route_cell.name,
    "power_stitch_policy" => "top/bottom M5 wrapper rails only; long per-leaf M5 taps disabled pending dedicated PDN routing",
    "placement_csv" => item.fetch("placement_csv"),
    "routes_csv" => item.fetch("routes_csv"),
    "instances_expected" => instances.length,
    "route_records" => route_rows.length,
    "route_shapes" => route_shapes,
    "density_fill_shapes" => density_fill_shapes,
    "density_fill_policy" => "disabled in column_periphery_routes; use a dedicated signoff fill step after routed connectivity is closed",
    "cleared_core_fill_shapes" => cleared_fill_shapes,
    "direct_child_counts" => counts.sort.to_h,
    "bbox_before_um" => old_bbox,
    "bbox_after_um" => bbox,
    "detail" => detail
  }
end

status = results.all? { |item| item.fetch("status") == "PASS" } ? "PASS" : "FAIL"
smoke_report = File.join(OUT, "gf180mcu_3v3_12t_2r2w_sram_512x8", "main_drc.lyrdb")
smoke_items = lyrdb_items(smoke_report)
manifest = {
  "package" => "gf180mcu-3v3-12t-2r2w-sram-macro",
  "status" => status,
  "scope" => "physically wrapped macro GDS with column periphery leaf instances, data/control routes, and BL landing trunks",
  "placement_manifest" => rel(PLAN),
  "smoke_main_drc" => smoke_items.nil? ? nil : {
    "macro" => "gf180mcu_3v3_12t_2r2w_sram_512x8",
    "status" => smoke_items.zero? ? "PASS" : "FAIL",
    "violations" => smoke_items,
    "report" => rel(smoke_report)
  },
  "results" => results
}
FileUtils.mkdir_p(OUT)
File.write(File.join(OUT, "MANIFEST.json"), JSON.pretty_generate(manifest) + "\n")

lines = [
  "# Column Periphery GDS Merge",
  "",
  "The published macro GDS tops are compact hybrid wrappers containing the original array/control core, per-bit read/write column leaves, route geometry, and top/bottom M5 wrapper rails. The placement consumes existing top/bottom control bands before growing the wrapper, and clears only local old density/fill keepouts under the new column leaves. The route wrapper intentionally emits no manual dummy fill/poly; density closure belongs in a separate signoff fill step after routed connectivity is closed. Long per-leaf M5 power taps are intentionally disabled until a dedicated PDN router is added.",
  "",
  "| Macro | Status | Instances | Routes | Route shapes | New bbox |",
  "| --- | --- | ---: | ---: | ---: | --- |"
]
results.each do |item|
  bbox = item.fetch("bbox_after_um")
  lines << "| `#{item.fetch('macro')}` | `#{item.fetch('status')}` | #{item.fetch('instances_expected')} | #{item.fetch('route_records')} | #{item.fetch('route_shapes')} | `#{bbox['width_um']}um x #{bbox['height_um']}um` |"
end
unless smoke_items.nil?
  lines += [
    "",
    "Smoke DRC:",
    "",
    "- `gf180mcu_3v3_12t_2r2w_sram_512x8`: GF180 KLayout `main.drc` #{smoke_items.zero? ? 'PASS' : 'FAIL'}, `#{smoke_items}` violations, report `#{rel(smoke_report)}`."
  ]
end
File.write(File.join(OUT, "README.md"), lines.join("\n") + "\n")

puts "GF180MCU 12T SRAM column periphery GDS merge: #{status}"
puts File.join(OUT, "MANIFEST.json")
exit(status == "PASS" ? 0 : 1)
