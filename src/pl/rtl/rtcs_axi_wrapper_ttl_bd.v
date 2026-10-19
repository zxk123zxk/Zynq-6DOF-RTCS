`timescale 1ns / 1ps
// Physical G1 wrapper. g1_inhibit is pulled high at the package pin: an
// explicit J20-36 to J20-38 ground strap is required to transmit. Removing
// the strap aborts an active frame; software cannot override this input.
module rtcs_axi_wrapper_ttl_bd (
  input wire s_axi_aclk, input wire s_axi_aresetn,
  input wire [31:0] s_axi_awaddr, input wire s_axi_awvalid, output wire s_axi_awready,
  input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
  input wire s_axi_wvalid, output wire s_axi_wready,
  output wire [1:0] s_axi_bresp, output wire s_axi_bvalid, input wire s_axi_bready,
  input wire [31:0] s_axi_araddr, input wire s_axi_arvalid, output wire s_axi_arready,
  output wire [31:0] s_axi_rdata, output wire [1:0] s_axi_rresp,
  output wire s_axi_rvalid, input wire s_axi_rready, output wire irq,
  input wire servo_ttl_rx, output wire servo_ttl_tx, input wire g1_inhibit
);
  wire tx_data;
  wire tx_enable;

  // 限位在这里是字面量而不是 g2_board_limits_pkg::SAFE_MAX：BD 的 module reference
  // 顶必须是 Verilog(.v)，Verilog 不能引用 SystemVerilog 包常量，所以只能复制一份。
  // 代价是两处必须同步——scripts/check_limit_sync.py 会同时校验 pkg 与本文件，
  // 不同步就在回归第一步失败，不会等到板端 move-six 才报 fault=12。
  // 当前值对应 config/g2_measured_limits.toml（2026-10-17 六工位示教实测）。
  rtcs_top #(
    .G1_TTL_PORTS(1'b1),
    .G2_CALIBRATED_MASK(6'h3f),
    .G2_SAFE_MIN({32'd2050,32'd0,32'd2000,32'd2000,32'd861,32'd1000}),
    .G2_SAFE_MAX({32'd3000,32'd4000,32'd3100,32'd3117,32'd2500,32'd3000}),
    .G2_REFERENCE({32'd2092,32'd2000,32'd2861,32'd3117,32'd861,32'd2000}),
    .G2_SPEED_MAX_RAW(16'd1500)
  ) u_rtcs_top (
    .s_axi_aclk(s_axi_aclk), .s_axi_aresetn(s_axi_aresetn),
    .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
    .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
    .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
    .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
    .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
    .servo_rx(servo_ttl_rx), .servo_tx(tx_data), .servo_tx_en(tx_enable),
    .estop_n(!g1_inhibit), .irq(irq)
  );

  // Explicit I/O primitive: Vivado may convert a tri-state inferred inside
  // a BD module reference into ordinary logic instead of a package-pin TBUF.
  OBUFT u_servo_tx_iobuf (.I(tx_data), .T(!tx_enable), .O(servo_ttl_tx));
endmodule
