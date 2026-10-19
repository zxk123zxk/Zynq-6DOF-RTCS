package g2_board_limits_pkg;
  // Installed arm measurements. 注意下文字面量是"高位在前"：列表里第一个数落在
  // index 5，也就是 ID 6；ID 1 在最右边。读这段表时按 ID n -> index n-1 反着看。
  // 本包是非 TTL 变体（rtcs_axi_wrapper_bd -> rtcs_top 默认参数）用的；
  // 生产板走 TTL 变体，限位在 rtcs_axi_wrapper_ttl_bd.v 里另有一份字面量副本
  // （BD 的 module reference 顶必须是 Verilog，Verilog 不能引用 SV 包常量）。
  // 改限位必须两处同改：scripts/check_limit_sync.py 会一起校验。
  // ID 6 was recalibrated on 2026-10-13; the operator confirmed 2050..3050 reachable
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
