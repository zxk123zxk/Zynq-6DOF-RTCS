package g2_board_limits_pkg;
  // Installed arm measurements, ID 1 at packed index 0. ID 6 was
  // recalibrated on 2026-10-13; the operator confirmed 2050..3050 reachable
  // without interference and selected a 2050..3000 command interval.
  localparam logic [5:0] CALIBRATED_MASK = 6'h3f;
  localparam logic [5:0][31:0] SAFE_MIN = {
    32'd2050, 32'd0, 32'd2000, 32'd2000, 32'd861, 32'd1000
  };
  localparam logic [5:0][31:0] SAFE_MAX = {
    32'd3000, 32'd4000, 32'd3100, 32'd3117, 32'd2500, 32'd3000
  };
  // ID 6 reference 2092 is the 2026-10-13 static READ, not a safe return pose.
  // Other references remain historical measurements; none is a safe return pose.
  // 2026-10-17 六工位示教实测：ID2 可达 2433、ID4 可达 3009（calibrate-step，servo_error=0），
  // 据此把 SAFE_MAX 的 ID2 1500→2500、ID4 2861→3100。config/g2_measured_limits.toml 同步。
  localparam logic [5:0][31:0] REFERENCE = {
    32'd2092, 32'd2000, 32'd2861, 32'd3117, 32'd861, 32'd2000
  };
  localparam logic [15:0] SPEED_MAX_RAW = 16'd1500;
endpackage
