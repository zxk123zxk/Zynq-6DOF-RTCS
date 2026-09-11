`timescale 1ns / 1ps
// Verilog-only BD top required by Vivado 2023.2 module-reference inference.
// The underlying rtcs_top is SystemVerilog.  No physical servo ports exist in
// G0; the core internally keeps its transmitter disabled.
module rtcs_axi_wrapper_bd (
  input wire s_axi_aclk, input wire s_axi_aresetn,
  input wire [31:0] s_axi_awaddr, input wire s_axi_awvalid, output wire s_axi_awready,
  input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
  input wire s_axi_wvalid, output wire s_axi_wready,
  output wire [1:0] s_axi_bresp, output wire s_axi_bvalid, input wire s_axi_bready,
  input wire [31:0] s_axi_araddr, input wire s_axi_arvalid, output wire s_axi_arready,
  output wire [31:0] s_axi_rdata, output wire [1:0] s_axi_rresp,
  output wire s_axi_rvalid, input wire s_axi_rready, output wire irq
);
  wire unused_servo_tx;
  wire unused_servo_tx_en;

  rtcs_top u_rtcs_top (
    .s_axi_aclk(s_axi_aclk), .s_axi_aresetn(s_axi_aresetn),
    .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
    .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
    .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
    .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
    .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
    .servo_rx(1'b1), .servo_tx(unused_servo_tx), .servo_tx_en(unused_servo_tx_en),
    .estop_n(1'b1), .irq(irq)
  );
endmodule
