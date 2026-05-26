#!/usr/bin/env ruby
# Physically merge placed Avalon control stdcells into the published macro GDS.

require "csv"
require "fileutils"
require "json"

ROOT = File.expand_path("..", __dir__)
PLACEMENT_MANIFEST = File.join(ROOT, "reports", "stdcell_control_placement", "MANIFEST.json")
AVALON_GDS = File.join(
  ROOT,
  "third_party", "gf180mcu_as_sc_mcu7t3v3", "pdk", "libs.ref",
  "gf180mcu_as_sc_mcu7t3v3", "gf180mcu_as_sc_mcu7t3v3__merged.gds"
)
OUT = File.join(ROOT, "reports", "stdcell_control_gds_merge")

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
  layout.each_cell do |cell|
    return cell if cell.name == name
  end
  nil
end

def dbu(value_um, layout)
  (value_um.to_f / layout.dbu).round
end

def def_orient_trans(orient, x, y, width, height)
  case orient
  when "N"
    RBA::Trans.new(RBA::Trans::R0, x, y)
  when "S"
    RBA::Trans.new(RBA::Trans::R180, x + width, y + height)
  when "FN"
    RBA::Trans.new(RBA::Trans::M90, x + width, y)
  when "FS"
    RBA::Trans.new(RBA::Trans::M0, x, y + height)
  else
    raise "unsupported DEF orientation #{orient.inspect}"
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

raise "missing placement manifest: #{PLACEMENT_MANIFEST}" unless File.file?(PLACEMENT_MANIFEST)
raise "missing Avalon merged GDS: #{AVALON_GDS}" unless File.file?(AVALON_GDS)

FileUtils.mkdir_p(OUT)
placement = JSON.parse(File.read(PLACEMENT_MANIFEST))
results = []

placement.fetch("results").each do |item|
  macro = item.fetch("macro")
  macro_gds = File.join(ROOT, "macros", macro, "layout", "#{macro}.gds")
  csv_path = File.join(ROOT, item.fetch("placement_csv"))
  raise "missing macro GDS: #{macro_gds}" unless File.file?(macro_gds) && File.size(macro_gds).positive?
  raise "missing placement CSV: #{csv_path}" unless File.file?(csv_path) && File.size(csv_path).positive?

  instances = CSV.read(csv_path, headers: true).map(&:to_h)
  expected_counts = Hash.new(0)
  instances.each { |inst| expected_counts[inst.fetch("cell")] += 1 }

  layout = RBA::Layout.new
  layout.read(macro_gds)
  top = find_cell(layout, macro)
  raise "missing top cell #{macro} in #{macro_gds}" unless top
  target = find_cell(layout, "#{macro}_array_control_core") || top

  existing_counts = direct_child_counts(layout, target).select { |name, _| name.start_with?("gf180mcu_as_sc_mcu7t3v3__") }
  already_integrated = expected_counts.all? { |name, count| existing_counts[name].to_i >= count }
  status = "PASS"
  detail = []
  inserted = 0

  unless already_integrated
    if existing_counts.values.sum.positive?
      raise "#{macro}: partial existing Avalon stdcell placement in GDS; regenerate from clean base before merging"
    end

    layout.read(AVALON_GDS)
    instances.each do |inst|
      child = find_cell(layout, inst.fetch("cell"))
      raise "#{macro}: missing stdcell #{inst.fetch('cell')} in #{AVALON_GDS}" unless child

      x = dbu(inst.fetch("x_um"), layout)
      y = dbu(inst.fetch("y_um"), layout)
      width = dbu(inst.fetch("width_um"), layout)
      height = dbu(inst.fetch("height_um"), layout)
      trans = def_orient_trans(inst.fetch("orient"), x, y, width, height)
      target.insert(RBA::CellInstArray.new(child.cell_index, trans))
      inserted += 1
    end
  end

  final_counts = direct_child_counts(layout, target).select { |name, _| name.start_with?("gf180mcu_as_sc_mcu7t3v3__") }
  missing = expected_counts.select { |name, count| final_counts[name].to_i < count }
  unless missing.empty?
    status = "FAIL"
    detail << "stdcell direct instance count below expected ordinary-control floor: #{missing.inspect}"
  end

  bbox = bbox_um(target, layout)
  width_ok = (bbox.fetch("width_um") - item.fetch("macro_width_um").to_f).abs <= 0.001
  height_ok = (bbox.fetch("height_um") - item.fetch("macro_height_um").to_f).abs <= 0.001
  unless width_ok && height_ok
    status = "FAIL"
    detail << "bbox changed: #{bbox}"
  end

  if status == "PASS" && !already_integrated
    tmp = "#{macro_gds}.tmp_gds_merge.gds"
    layout.write(tmp)
    FileUtils.mv(tmp, macro_gds)
  end

  results << {
    "macro" => macro,
    "status" => status,
    "gds" => rel(macro_gds),
    "target_cell" => target.name,
    "wrapped_top" => target.name != top.name,
    "source_placement_csv" => rel(csv_path),
    "already_integrated" => already_integrated,
    "inserted_instances" => inserted,
    "expected_instances" => instances.length,
    "direct_avalon_instance_counts" => expected_counts.sort.to_h,
    "actual_direct_avalon_instance_counts" => final_counts.sort.to_h,
    "bbox_um" => bbox,
    "footprint_unchanged" => width_ok && height_ok,
    "detail" => detail
  }
end

status = results.all? { |item| item.fetch("status") == "PASS" } ? "PASS" : "FAIL"
manifest = {
  "package" => "gf180mcu-3v3-12t-2r2w-sram-macro",
  "status" => status,
  "scope" => "physically merged Avalon stdcell control GDS instances into macros/*/layout GDS files",
  "avalon_gds" => rel(AVALON_GDS),
  "placement_manifest" => rel(PLACEMENT_MANIFEST),
  "results" => results
}
File.write(File.join(OUT, "MANIFEST.json"), JSON.pretty_generate(manifest) + "\n")

lines = [
  "# Stdcell Control GDS Merge",
  "",
  "Avalon stdcell control gates are physically instantiated in the published macro GDS files.",
  "This merge does not change macro width or height.",
  "",
  "| Macro | Status | Inserted | Expected | Footprint |",
  "| --- | --- | ---: | ---: | --- |"
]
results.each do |item|
  lines << "| `#{item.fetch('macro')}` | `#{item.fetch('status')}` | #{item.fetch('inserted_instances')} | #{item.fetch('expected_instances')} | `#{item.fetch('footprint_unchanged')}` |"
end
File.write(File.join(OUT, "README.md"), lines.join("\n") + "\n")

puts "GF180MCU 12T SRAM stdcell GDS merge: #{status}"
puts File.join(OUT, "MANIFEST.json")
exit(status == "PASS" ? 0 : 1)
