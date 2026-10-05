`timescale 1ns / 1ps
module OBUFT(input wire I, T, output wire O);
  assign O = T ? 1'bz : I;
endmodule

module tb_rtcs_g1_ttl_top;
  logic clk = 0, rst_n = 0, inhibit = 1;
  logic [31:0] awaddr = 0, wdata = 0, araddr = 0;
  logic [3:0] wstrb = 0;
  logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  wire awready, wready, bvalid, arready, rvalid, irq;
  wire [1:0] bresp, rresp;
  wire [31:0] rdata;
  tri1 servo_ttl_tx;
  logic tx_seen = 0;
  always #5 clk = ~clk;

  rtcs_axi_wrapper_ttl_bd dut (
    .s_axi_aclk(clk), .s_axi_aresetn(rst_n),
    .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
    .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
    .servo_ttl_rx(1'b1), .servo_ttl_tx(servo_ttl_tx), .g1_inhibit(inhibit), .irq(irq)
  );

  always @(posedge clk) begin
    if (inhibit && dut.tx_enable !== 1'b0) $fatal(1, "inhibit failed to gate TX");
    if (!inhibit && dut.tx_enable && !servo_ttl_tx) tx_seen <= 1;
  end

  task automatic write32(input logic [31:0] address, input logic [31:0] value);
    @(negedge clk); awaddr = address; awvalid = 1; wdata = value; wstrb = 4'hf; wvalid = 1;
    @(posedge clk); if (!awready || !wready) $fatal(1, "AXI write not accepted");
    @(negedge clk); awvalid = 0; wvalid = 0;
    wait(bvalid); if (bresp != 0) $fatal(1, "AXI write error");
    @(negedge clk); bready = 1;
    @(negedge clk); bready = 0;
  endtask

  task automatic read32(input logic [31:0] address, output logic [31:0] value);
    @(negedge clk); araddr = address; arvalid = 1;
    @(posedge clk); if (!arready) $fatal(1, "AXI read not accepted");
    @(negedge clk); arvalid = 0;
    wait(rvalid); if (rresp != 0) $fatal(1, "AXI read error");
    value = rdata;
    @(negedge clk); rready = 1;
    @(negedge clk); rready = 0;
  endtask

  logic [31:0] value;
  initial begin
    repeat (5) @(negedge clk); rst_n = 1;
    read32(32'h00, value);
    if (value !== 32'h5254_0003) $fatal(1, "new pinout ABI not visible");
    read32(32'h5c, value);
    if (!value[3]) $fatal(1, "unstrapped TX not disabled");
    write32(32'h50, 1); write32(32'h54, 1); write32(32'h58, 1);
    repeat (20) @(negedge clk);
    read32(32'h5c, value);
    if (!value[3] || value[0] || tx_seen) $fatal(1, "unstrapped command transmitted");

    inhibit = 0;
    read32(32'h5c, value);
    if (value[3]) $fatal(1, "strapped TX still disabled");
    write32(32'h50, 1); write32(32'h54, 1); write32(32'h58, 1);
    repeat (150) @(negedge clk);
    if (!tx_seen) $fatal(1, "strapped PING did not reach pin");
    inhibit = 1;
    #1;
    if (dut.tx_enable !== 1'b0 || servo_ttl_tx !== 1'b1)
      $fatal(1, "removing strap did not immediately release TX");
    repeat (5) @(negedge clk);
    read32(32'h5c, value);
    if (!value[3] || value[2:0] != 0) $fatal(1, "abort did not clear state");
    inhibit = 0;
    repeat (20) @(negedge clk);
    if (dut.tx_enable !== 1'b0) $fatal(1, "rearming resumed partial frame");
    $display("TB_RTCS_G1_TTL_TOP_PASS");
    $finish;
  end
endmodule
