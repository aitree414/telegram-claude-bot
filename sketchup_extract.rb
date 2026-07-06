# SketchUp Component Extractor
# Run this from Ruby Console:  load '/Users/aitree414/telegram-claude-bot/sketchup_extract.rb'

require 'json'

def extract_all
  model = Sketchup.active_model
  unless model
    puts "No active model!"
    return
  end

  output_path = "/tmp/sketchup_items.json"
  all_items = []

  model.entities.each do |entity|
    next unless entity.is_a?(Sketchup::ComponentInstance) || entity.is_a?(Sketchup::Group)
    begin
      bb = entity.bounds
      defn = entity.respond_to?(:definition) ? entity.definition : nil
      all_items << {
        name: entity.name.to_s.empty? ? "unnamed_#{entity.entityID}" : entity.name.to_s,
        definition: defn ? defn.name.to_s : "",
        layer: entity.layer ? entity.layer.name.to_s : "",
        material: entity.material ? entity.material.name.to_s : "",
        mm: [bb.width.to_mm.round(0), bb.depth.to_mm.round(0), bb.height.to_mm.round(0)],
        pos: [entity.transformation.origin.x.to_mm.round(0),
              entity.transformation.origin.y.to_mm.round(0),
              entity.transformation.origin.z.to_mm.round(0)],
      }
    rescue => e
      all_items << { name: "error", error: e.message }
    end
  end

  output = {
    model: model.title,
    path: model.path,
    count: all_items.length,
    items: all_items,
  }

  File.write(output_path, JSON.pretty_generate(output))
  puts "Done! #{all_items.length} items extracted."
  puts "Output: #{output_path}"
end

extract_all
