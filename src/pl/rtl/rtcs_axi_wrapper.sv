`timescale 1ns / 1ps
// Block-Design-facing wrapper for the phase-0 RTCS peripheral.
//
// It intentionally does not expose any servo pins.  Until G1 has proved the
// electrical PHY and the independent E-stop path, the core sees an inactive
// E-stop and its servo transmitter remains permanently disabled internally.
module rtcs_axi_wrapper (
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
  output logic         irq
);
  logic unused_servo_tx;
  logic unused_servo_tx_en;

  rtcs_top u_rtcs_top (
    .s_axi_aclk, .s_axi_aresetn,
    .s_axi_awaddr, .s_axi_awvalid, .s_axi_awready,
    .s_axi_wdata, .s_axi_wstrb, .s_axi_wvalid, .s_axi_wready,
    .s_axi_bresp, .s_axi_bvalid, .s_axi_bready,
    .s_axi_araddr, .s_axi_arvalid, .s_axi_arready,
    .s_axi_rdata, .s_axi_rresp, .s_axi_rvalid, .s_axi_rready,
    .servo_rx(1'b1),
    .servo_tx(unused_servo_tx),
    .servo_tx_en(unused_servo_tx_en),
    .estop_n(1'b1),
    .irq
  );
endmodule
