// Interface reservation. Implement trapezoidal profiles only after the joint
// unit, limits and servo timing have been measured and frozen.
module trajectory_engine #(
  parameter int unsigned AXIS_COUNT = 6
) (
  input logic clk, input logic rst_n, input logic command_valid,
  input logic [31:0] target [0:AXIS_COUNT-1], input logic [31:0] speed,
  input logic [31:0] accel, input logic [63:0] deadline,
  output logic busy, output logic deadline_miss
);
  always_ff @(posedge clk) begin
    if (!rst_n) begin busy <= 1'b0; deadline_miss <= 1'b0; end
    else if (command_valid) begin busy <= 1'b0; deadline_miss <= 1'b0; end
  end
endmodule
