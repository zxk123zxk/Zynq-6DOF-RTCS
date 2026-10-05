`timescale 1ns/1ps
module tb_hx30hm_g1_engine;
  logic clk = 0, rst_n = 0, clear = 0, start = 0, rx = 1;
  logic [7:0] id = 1, op = 1;
  wire tx, tx_enable, busy, done;
  wire [3:0] fault;
  wire [7:0] servo_error;
  wire [15:0] position;
  wire [7:0] observed_tx;
  wire observed_valid, observed_fault;
  logic [7:0] sent [0:7];
  integer sent_count = 0;
  always #5 clk = ~clk;

  hx30hm_g1_engine #(.RESPONSE_TIMEOUT_TICKS(12000)) dut (
    .clk(clk), .rst_n(rst_n), .clear(clear), .start(start),
    .target_id(id), .operation(op), .rx(rx), .tx(tx), .tx_enable(tx_enable),
    .busy(busy), .done(done), .fault_code(fault),
    .servo_error(servo_error), .position_raw(position));
  uart_byte_rx observer (.clk(clk), .rst_n(rst_n), .clear(1'b0), .rx(tx),
    .data(observed_tx), .valid(observed_valid), .framing_fault(observed_fault));
  always @(posedge clk) if (observed_valid) begin
    if (sent_count >= 8) $fatal(1, "too many transmitted bytes");
    sent[sent_count] = observed_tx;
    sent_count = sent_count + 1;
  end

  task automatic request(input logic [7:0] req_id, input logic [7:0] req_op);
    @(negedge clk); id = req_id; op = req_op; start = 1;
    @(negedge clk); start = 0;
  endtask
  task automatic reset_result;
    @(negedge clk); clear = 1;
    @(negedge clk); clear = 0; sent_count = 0;
  endtask
  task automatic send_byte(input logic [7:0] value);
    @(negedge clk); rx = 0; repeat (100) @(negedge clk);
    for (integer i = 0; i < 8; i = i + 1) begin
      rx = value[i]; repeat (100) @(negedge clk);
    end
    rx = 1; repeat (100) @(negedge clk);
  endtask
  initial begin
    repeat (5) @(negedge clk); rst_n = 1;
    if (tx_enable !== 0 || tx !== 1) $fatal(1, "reset did not release TX");
    request(1, 1);
    wait(tx_enable); wait(!tx_enable);
    if (sent_count != 6 || sent[0] != 8'hff || sent[1] != 8'hff ||
        sent[2] != 1 || sent[3] != 2 || sent[4] != 1 || sent[5] != 8'hfb)
      $fatal(1, "PING request mismatch");
    send_byte(8'hff); send_byte(8'hff); send_byte(1);
    send_byte(2); send_byte(0); send_byte(8'hfc);
    wait(done);
    if (fault != 0 || servo_error != 0) $fatal(1, "PING response rejected");
    reset_result();

    request(1, 2);
    wait(tx_enable); wait(!tx_enable);
    if (sent_count != 8 || sent[4] != 2 || sent[5] != 8'h38 ||
        sent[6] != 2 || sent[7] != 8'hbe)
      $fatal(1, "READ request mismatch");
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(4);
    send_byte(0); send_byte(8'h18); send_byte(8'h05); send_byte(8'hdd);
    wait(done);
    if (fault != 0 || position != 16'h0518) $fatal(1, "READ position mismatch");
    reset_result();

    request(1, 1);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1);
    send_byte(2); send_byte(0); send_byte(8'h00);
    wait(done);
    if (fault != 7 || tx_enable != 0) $fatal(1, "bad checksum accepted");
    reset_result();

    request(1, 1);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(2);
    wait(done);
    if (fault != 6 || tx_enable != 0) $fatal(1, "wrong response ID accepted");
    reset_result();

    request(1, 1);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(4);
    wait(done);
    if (fault != 4) $fatal(1, "wrong response length accepted");
    reset_result();

    request(1, 1);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1);
    send_byte(2); send_byte(4); send_byte(8'hf8);
    wait(done);
    if (fault != 8 || servo_error != 4) $fatal(1, "servo error not reported");
    reset_result();

    request(8'hfe, 1);
    wait(done);
    if (fault != 1 || tx_enable != 0 || sent_count != 0)
      $fatal(1, "broadcast ID was not rejected");
    reset_result();
    request(1, 3);
    wait(done);
    if (fault != 2 || tx_enable != 0 || sent_count != 0)
      $fatal(1, "WRITE opcode was not rejected");
    reset_result();

    request(1, 1);
    wait(tx_enable); wait(!tx_enable); wait(done);
    if (fault != 3 || tx_enable != 0) $fatal(1, "timeout failed");
    reset_result();
    request(1, 1);
    wait(tx_enable);
    @(negedge clk); clear = 1;
    #1;
    if (tx_enable != 0) $fatal(1, "clear did not immediately disable TX direction");
    @(negedge clk); clear = 0;
    if (busy || done || fault != 0 || tx !== 1)
      $fatal(1, "clear failed to abort transmission");
    $display("TB_HX30HM_G1_ENGINE_PASS");
    $finish;
  end
endmodule
