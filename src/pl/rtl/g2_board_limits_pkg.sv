package g2_board_limits_pkg;
  // Installed arm measurements, ID 1 at packed index 0.
  localparam logic [5:0] CALIBRATED_MASK = 6'h3f;
  localparam logic [5:0][31:0] SAFE_MIN = {
    32'd1585, 32'd0, 32'd2000, 32'd2000, 32'd861, 32'd1000
  };
  localparam logic [5:0][31:0] SAFE_MAX = {
    32'd2500, 32'd4000, 32'd2861, 32'd3117, 32'd1500, 32'd3000
  };
  // 测得的参考位置，其中多轴恰在限位端点；不是自动回位姿态。
  localparam logic [5:0][31:0] REFERENCE = {
    32'd1585, 32'd2000, 32'd2861, 32'd3117, 32'd861, 32'd2000
  };
  localparam logic [15:0] SPEED_MAX_RAW = 16'd1500;
endpackage
