`timescale 1ns / 1ps
module rtcs_top #(
  parameter int unsigned AXIS_COUNT = 6
) (
  input  logic         s_axi_aclk,
  input  logic         s_axi_aresetn,
  input  logic [31:0]  s_axi_awaddr,
  input  logic         s_axi_awvalid,
  output logic         s_axi_awready,
  input  logic [31:0]  s_axi_wdata,
  input  logic [3:0]   s_axi_wstrb,
  input  logic         s_axi_wvalid,
  output logic         s_axi_wready,
  output logic [1:0]   s_axi_bresp,
  output logic         s_axi_bvalid,
  input  logic         s_axi_bready,
  input  logic [31:0]  s_axi_araddr,
  input  logic         s_axi_arvalid,
  output logic         s_axi_arready,
  output logic [31:0]  s_axi_rdata,
  output logic [1:0]   s_axi_rresp,
  output logic         s_axi_rvalid,
  input  logic         s_axi_rready,
  input  logic         servo_rx,
  output logic         servo_tx,
  output logic         servo_tx_en,
  input  logic         estop_n,
  output logic         irq
);
  // 这些内部信号是 AXI 寄存器组与后续运动/总线模块之间的接口。
  logic [63:0] hw_ticks;
  logic [31:0] control, command, status, irq_status, profile_speed, profile_accel, servo_config;
  logic [63:0] deadline;
  logic [31:0] target [0:AXIS_COUNT-1];
  (* mark_debug = "true" *) logic [7:0] rx_observed_byte;
  (* mark_debug = "true" *) logic rx_observed_valid;
  (* mark_debug = "true" *) logic rx_protocol_fault;
  (* mark_debug = "true" *) logic tx_direction_disabled;

  // 100 MHz AXI 时钟域的自由运行时间戳，供 PS 设置绝对截止时间。
  always_ff @(posedge s_axi_aclk) begin
    if (!s_axi_aresetn) hw_ticks <= '0;
    else               hw_ticks <= hw_ticks + 64'd1;
  end

  // AXI 互连提供完整 32 位地址；寄存器组只需要低 8 位的外设内偏移。
  axi_lite_regs #(.AXI_ADDR_WIDTH(8), .AXIS_COUNT(AXIS_COUNT)) u_axi_lite_regs (
    .aclk(s_axi_aclk), .aresetn(s_axi_aresetn),
    .saxi_awaddr(s_axi_awaddr[7:0]), .saxi_awvalid(s_axi_awvalid), .saxi_awready(s_axi_awready),
    .saxi_araddr(s_axi_araddr[7:0]), .saxi_arvalid(s_axi_arvalid), .saxi_arready(s_axi_arready),
    .saxi_wready(s_axi_wready), .saxi_wvalid(s_axi_wvalid), .saxi_wdata(s_axi_wdata), .saxi_wstrb(s_axi_wstrb),
    .saxi_rready(s_axi_rready), .saxi_rvalid(s_axi_rvalid), .saxi_rdata(s_axi_rdata), .saxi_rresp(s_axi_rresp),
    .saxi_bready(s_axi_bready), .saxi_bvalid(s_axi_bvalid), .saxi_bresp(s_axi_bresp),
    .hw_ticks(hw_ticks), .status(status), .irq_status(irq_status),
    .control(control), .command(command), .target(target), .profile_speed(profile_speed),
    .profile_accel(profile_accel), .deadline(deadline), .servo_config(servo_config)
  );

  servo_bus_master u_rx_observer (
    .clk(s_axi_aclk), .rst_n(s_axi_aresetn), .rx(servo_rx),
    .tx(), .tx_enable(tx_direction_disabled), .protocol_fault(rx_protocol_fault),
    .observed_byte(rx_observed_byte), .observed_valid(rx_observed_valid)
  );

  // 第 0 阶段的失效安全策略：发送端始终高阻。仅在安全监控器和物理层通过
  // docs/0.1hardware_bringup.md 的上板门禁后，才可替换此逻辑。
  always_comb begin
    servo_tx    = 1'b1;
    servo_tx_en = 1'b0;
    irq         = 1'b0;
    status      = {30'd0, !estop_n, 1'b1}; // bit 0：安全禁用；bit 1：急停有效
    irq_status  = 32'd0;
  end
endmodule
