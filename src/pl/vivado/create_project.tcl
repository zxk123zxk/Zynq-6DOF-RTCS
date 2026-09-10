# Reproducible project shell for the AX7020. Verify the exact part against the
# board before generating a production XSA.
set script_dir [file dirname [file normalize [info script]]]
set project_root [file normalize "$script_dir/../../.."]
set project_name zynq_rtcs
set project_dir "$project_root/build/vivado/$project_name"
set part xc7z020clg400-2

create_project $project_name $project_dir -part $part -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

add_files [glob -nocomplain "$project_root/src/pl/rtl/*.sv"]
add_files -fileset constrs_1 "$project_root/src/pl/xdc/ax7020_template.xdc"
set_property top rtcs_top [current_fileset]

puts "Created RTL shell. Next: add/configure Processing System 7 and AXI interconnect."
puts "Do not use the template XDC for a live servo bus."
