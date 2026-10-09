`timescale 1ns / 1ps
// Proves that an AXI G1 request cannot reach physical outputs in the safe BD.
module tb_rtcs_g1_safe_top;
  logic clk = 0, rst_n = 0;
  logic [31:0] awaddr = 0, wdata = 0, araddr = 0;
  logic [3:0] wstrb = 0;
  logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
  wire awready, wready, bvalid, arready, rvalid, servo_tx, servo_tx_en, irq;
  wire [1:0] bresp, rresp;
  wire [31:0] rdata;
  logic internal_tx_seen = 0;
  always #5 clk = ~clk;

  rtcs_top dut (
    .s_axi_aclk(clk), .s_axi_aresetn(rst_n),
    .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
    .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
    .servo_rx(1'b1), .servo_tx(servo_tx), .servo_tx_en(servo_tx_en),
    .estop_n(1'b1), .irq(irq)
  );

  always @(posedge clk) begin
    if (servo_tx !== 1'b1 || servo_tx_en !== 1'b0)
      $fatal(1, "safe top exposed G1 UART to a physical output");
    if (rst_n && dut.g1_internal_tx_en && !dut.g1_internal_tx)
      internal_tx_seen <= 1'b1;
  end

  task automatic write32(input logic [31:0] address, input logic [31:0] value);
    @(negedge clk);
    awaddr = address; awvalid = 1;
    wdata = value; wstrb = 4'hf; wvalid = 1;
    @(posedge clk);
    if (!awready || !wready) $fatal(1, "AXI write address/data not accepted");
    @(negedge clk); awvalid = 0; wvalid = 0;
    wait(bvalid);
    if (bresp != 0) $fatal(1, "AXI write error");
    @(negedge clk); bready = 1;
    @(negedge clk); bready = 0;
  endtask

  task automatic read32(input logic [31:0] address, output logic [31:0] value);
    @(negedge clk); araddr = address; arvalid = 1;
    @(posedge clk);
    if (!arready) $fatal(1, "AXI read address not accepted");
    @(negedge clk); arvalid = 0;
    wait(rvalid);
    if (rresp != 0) $fatal(1, "AXI read error");
    value = rdata;
    @(negedge clk); rready = 1;
    @(negedge clk); rready = 0;
  endtask

  logic [31:0] value;
  initial begin
    repeat (5) @(negedge clk);
    rst_n = 1;
    read32(32'h00, value);
    if (value != 32'h5254_000c) $fatal(1, "wrong G1 ABI");
    read32(32'h5c, value);
    if (value[3] !== 1'b1) $fatal(1, "physical-disabled status missing");

    write32(32'h50, 1); // explicit single-cast ID
    write32(32'h54, 1); // PING only
    write32(32'h58, 1); // atomic start
    repeat (150) @(negedge clk);
    if (internal_tx_seen) $fatal(1, "safe wrapper unexpectedly started UART");
    read32(32'h5c, value);
    if (value[3] !== 1'b1 || value[0] !== 1'b0)
      $fatal(1, "safe G1 request status mismatch");
    write32(32'h58, 2); // abort without waiting for timeout
    repeat (5) @(negedge clk);
    read32(32'h5c, value);
    if (value[3] !== 1'b1 || value[2:0] != 0)
      $fatal(1, "G1 abort did not restore safe idle");
    $display("TB_RTCS_G1_SAFE_TOP_PASS");
    $finish;
  end
endmodule
