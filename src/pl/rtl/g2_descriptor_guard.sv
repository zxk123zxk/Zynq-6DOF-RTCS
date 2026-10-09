// G2 六轴描述符检查器：由六轴控制器实例化，综合时限位默认全未标定。
module g2_descriptor_guard #(
  parameter int unsigned AXIS_COUNT = 6
) (
  input  logic clk, rst_n, commit,
  input  logic [AXIS_COUNT-1:0][31:0] target,
  input  logic [31:0] speed, accel,
  input  logic [63:0] deadline, now_ticks,
  input  logic [AXIS_COUNT-1:0] calibrated,
  input  logic [AXIS_COUNT-1:0][31:0] safe_min,
  input  logic [AXIS_COUNT-1:0][31:0] safe_max,
  input  logic inhibit,
  output logic accepted, rejected,
  output logic [2:0] reject_code,
  output logic [AXIS_COUNT-1:0][31:0] snapshot_target,
  output logic [31:0] snapshot_speed, snapshot_accel,
  output logic [63:0] snapshot_deadline
);
  localparam logic [2:0] REJECT_NONE = 3'd0;
  localparam logic [2:0] REJECT_UNCALIBRATED = 3'd1;
  localparam logic [2:0] REJECT_INHIBIT = 3'd2;
  localparam logic [2:0] REJECT_DEADLINE = 3'd3;
  localparam logic [2:0] REJECT_LIMIT = 3'd4;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      accepted <= 1'b0;
      rejected <= 1'b0;
      reject_code <= REJECT_NONE;
      snapshot_speed <= '0;
      snapshot_accel <= '0;
      snapshot_deadline <= '0;
      for (int axis = 0; axis < AXIS_COUNT; axis++) snapshot_target[axis] <= '0;
    end else begin
      accepted <= 1'b0;
      rejected <= 1'b0;
      if (commit) begin : check_and_snapshot
        logic limits_ok;
        // Evaluate the live descriptor at the commit edge, not a cached
        // combinational result from an unpacked-array port.
        limits_ok = 1'b1;
        for (int axis = 0; axis < AXIS_COUNT; axis++) begin
          if ($signed(safe_min[axis]) > $signed(safe_max[axis]) ||
              safe_max[axis] > 32'd65535 || target[axis][31:16] != 0 ||
              $signed(target[axis]) < $signed(safe_min[axis]) ||
              $signed(target[axis]) > $signed(safe_max[axis]))
            limits_ok = 1'b0;
        end
        if (!(&calibrated)) begin
          rejected <= 1'b1;
          reject_code <= REJECT_UNCALIBRATED;
        end else if (inhibit) begin
          rejected <= 1'b1;
          reject_code <= REJECT_INHIBIT;
        end else if (deadline <= now_ticks) begin
          rejected <= 1'b1;
          reject_code <= REJECT_DEADLINE;
        end else if (!limits_ok) begin
          rejected <= 1'b1;
          reject_code <= REJECT_LIMIT;
        end else begin
          accepted <= 1'b1;
          reject_code <= REJECT_NONE;
          snapshot_speed <= speed;
          snapshot_accel <= accel;
          snapshot_deadline <= deadline;
          for (int axis = 0; axis < AXIS_COUNT; axis++) snapshot_target[axis] <= target[axis];
        end
      end
    end
  end
endmodule
