// 轨迹模块接口预留。只有在关节单位、机械限位和舵机时序均完成实测、冻结后，
// 才可在此实现梯形速度轨迹；当前模块不产生运动。
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
