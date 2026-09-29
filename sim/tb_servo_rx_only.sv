`timescale 1ns/1ps
module tb_servo_rx_only;
  logic clk = 0;
  logic rst_n = 0;
  logic rx = 1;
  logic tx, tx_enable, fault, valid;
  logic [7:0] observed;
  always #5 clk = ~clk;
  servo_bus_master dut (.clk(clk), .rst_n(rst_n), .rx(rx), .tx(tx),
    .tx_enable(tx_enable), .protocol_fault(fault),
    .observed_byte(observed), .observed_valid(valid));

  task automatic send_byte(input logic [7:0] value, input logic good_stop);
    rx = 0; repeat (100) @(posedge clk);
    for (int bitno = 0; bitno < 8; bitno++) begin
      rx = value[bitno]; repeat (100) @(posedge clk);
    end
    rx = good_stop; repeat (100) @(posedge clk);
    rx = 1; repeat (100) @(posedge clk);
  endtask

  always @(posedge clk) begin
    if (tx_enable !== 1'b0 || tx !== 1'b1) $fatal(1, "TX became active");
  end

  initial begin
    repeat (4) @(posedge clk);
    rst_n = 1;
    send_byte(8'hA5, 1'b1);
    if (observed !== 8'hA5 || fault !== 0) $fatal(1, "RX byte failed");
    send_byte(8'h3C, 1'b0);
    if (fault !== 1) $fatal(1, "Framing fault not latched");
    rst_n = 0; repeat (3) @(posedge clk);
    if (fault !== 0 || tx_enable !== 0) $fatal(1, "Reset failed");
    $display("TB_SERVO_RX_ONLY_PASS");
    $finish;
  end
endmodule
