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
  logic [7:0] sent [0:61];
  logic [5:0][15:0] sync_position, sync_speed, sync_time;
  integer sent_count = 0;
  always #5 clk = ~clk;

  hx30hm_g1_engine #(.RESPONSE_TIMEOUT_TICKS(12000)) dut (
    .clk(clk), .rst_n(rst_n), .clear(clear), .start(start),
    .target_id(id), .operation(op), .write_position(16'd2005),
    .write_speed(16'd50), .write_time(16'h1234),
    .sync_position(sync_position), .sync_speed(sync_speed),
    .sync_time(sync_time), .rx(rx),
    .tx(tx), .tx_enable(tx_enable),
    .busy(busy), .done(done), .fault_code(fault),
    .servo_error(servo_error), .position_raw(position));
  uart_byte_rx observer (.clk(clk), .rst_n(rst_n), .clear(1'b0), .rx(tx),
    .data(observed_tx), .valid(observed_valid), .framing_fault(observed_fault));
  always @(posedge clk) if (observed_valid) begin
    if (sent_count >= 62) $fatal(1, "too many transmitted bytes");
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

    request(1, 11);
    wait(tx_enable); wait(!tx_enable);
    if (sent_count != 8 || sent[4] != 2 || sent[5] != 8'h28 ||
        sent[6] != 1 || sent[7] != 8'hcf)
      $fatal(1, "READ torque request mismatch");
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(3);
    send_byte(0); send_byte(1); send_byte(8'hfa);
    wait(done);
    if (fault != 0 || position != 1) $fatal(1, "READ torque value mismatch");
    reset_result();
    request(1, 11);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(3);
    send_byte(0); send_byte(1); send_byte(8'h00);
    wait(done);
    if (fault != 7) $fatal(1, "bad torque READ checksum accepted");
    reset_result();
    request(1, 11);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(2);
    wait(done);
    if (fault != 6) $fatal(1, "wrong torque READ ID accepted");
    reset_result();
    request(1, 11);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(4);
    wait(done);
    if (fault != 4) $fatal(1, "wrong torque READ length accepted");
    reset_result();
    request(1, 11);
    wait(tx_enable); wait(!tx_enable);
    send_byte(8'hff); send_byte(8'hff); send_byte(1); send_byte(3);
    send_byte(4); send_byte(1); send_byte(8'hf6);
    wait(done);
    if (fault != 8 || servo_error != 4)
      $fatal(1, "torque READ servo error ignored");
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
    request(1, 8);
    wait(tx_enable); wait(!tx_enable);
    if (sent_count != 15 || sent[0] != 8'hff || sent[1] != 8'hff ||
        sent[2] != 1 || sent[3] != 8'h0b || sent[4] != 3 || sent[5] != 8'h28 ||
        sent[6] != 1 || sent[7] != 0 || sent[8] != 8'hd5 || sent[9] != 8'h07 ||
        sent[10] != 8'h34 || sent[11] != 8'h12 ||
        sent[12] != 8'h32 || sent[13] != 0 || sent[14] != 8'h73)
      $fatal(1, "torque+position WRITE frame/checksum mismatch");
    send_byte(8'hff); send_byte(8'hff); send_byte(1);
    send_byte(2); send_byte(0); send_byte(8'hfc);
    wait(done);
    if (fault != 0) $fatal(1, "torque+position WRITE response rejected");
    reset_result();

    request(1, 9);
    wait(tx_enable); wait(!tx_enable);
    if (sent_count != 8 || sent[0] != 8'hff || sent[1] != 8'hff ||
        sent[2] != 1 || sent[3] != 4 || sent[4] != 3 || sent[5] != 8'h28 ||
        sent[6] != 0 || sent[7] != 8'hcf)
      $fatal(1, "torque-off frame/checksum mismatch");
    send_byte(8'hff); send_byte(8'hff); send_byte(1);
    send_byte(2); send_byte(0); send_byte(8'hfc);
    wait(done);
    if (fault != 0) $fatal(1, "torque-off response rejected");
    reset_result();

    // 只写 0x2a 的旧帧已从引擎移除：操作码 3 必须被拒绝且不发任何字节。
    request(1, 3);
    wait(done);
    if (fault != 2 || tx_enable != 0 || sent_count != 0)
      $fatal(1, "removed position-only opcode was not rejected");
    reset_result();

    // 广播帧独立逐字节核对：0x28=1、加速度0、目标/原始时间/速度各轴分离。
    for (int axis = 0; axis < 6; axis++) begin
      sync_position[axis] = 16'(2000 + axis * 10);
      sync_speed[axis] = 16'(1500 + axis);
      sync_time[axis] = 16'(10 + axis);
    end
    request(8'hfe, 10);
    wait(tx_enable); wait(!tx_enable); wait(done);
    if (sent_count != 62 || sent[0] != 8'hff || sent[1] != 8'hff ||
        sent[2] != 8'hfe || sent[3] != 8'd58 || sent[4] != 8'h83 ||
        sent[5] != 8'h28 || sent[6] != 8'd8)
      $fatal(1, "SYNC WRITE header mismatch");
    for (int axis = 0; axis < 6; axis++) begin
      if (sent[7+axis*9] != 8'(axis+1) || sent[8+axis*9] != 1 ||
          sent[9+axis*9] != 0 ||
          sent[10+axis*9] != sync_position[axis][7:0] ||
          sent[11+axis*9] != sync_position[axis][15:8] ||
          sent[12+axis*9] != sync_time[axis][7:0] ||
          sent[13+axis*9] != sync_time[axis][15:8] ||
          sent[14+axis*9] != sync_speed[axis][7:0] ||
          sent[15+axis*9] != sync_speed[axis][15:8])
        $fatal(1, "SYNC WRITE axis %0d data mismatch",axis+1);
    end
    begin
      logic [7:0] sum;
      sum=0;
      for (int i=2; i<61; i++) sum=sum+sent[i];
      if (sent[61] != ~sum || fault != 0)
        $fatal(1, "SYNC WRITE checksum or no-reply completion mismatch");
    end
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
