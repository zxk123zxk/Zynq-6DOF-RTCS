`timescale 1ns / 1ps

module tb_hx30hm_protocol;
  import hx30hm_protocol_pkg::*;

  initial begin
    // Golden vectors copied from the supplied HX-30HM protocol document.
    if (checksum_ping(8'h01) !== 8'hfb)
      $fatal(1, "PING checksum mismatch");
    if (checksum_read(8'h01, ADDR_PRESENT_POSITION, 8'h02) !== 8'hbe)
      $fatal(1, "READ position checksum mismatch");
    // ABI 08 运动帧：0x28 起八字节，包含可变的目标、原始时间、原始速度。
    if (checksum_torque_move(8'h01, 16'h0800, 16'd0, 16'h03e8) !== 8'hd4)
      $fatal(1, "torque-move WRITE checksum mismatch");
    if (checksum_torque_move(8'h01, 16'd2080, 16'd0, 16'd50) !== 8'h6d)
      $fatal(1, "torque-move 2080 checksum mismatch");
    if (checksum_torque_move(8'h01, 16'd2080, 16'h1234, 16'd50) !== 8'h27)
      $fatal(1, "torque-move variable time checksum mismatch");
    // 卸力单字节写：0x28 <- 0。
    if (checksum_torque_off(8'h01) !== 8'hcf)
      $fatal(1, "torque-off checksum mismatch");
    // 帧长随操作码变化，不能再假设固定 13 字节。
    if (last_tx_index(OP_PING) !== 4'd5 || last_tx_index(OP_READ) !== 4'd7 ||
        last_tx_index(OP_TORQUE_MOVE) !== 4'd14 ||
        last_tx_index(OP_TORQUE_OFF) !== 4'd7)
      $fatal(1, "frame length table mismatch");
    if (OP_PING !== 8'd1 || OP_READ !== 8'd2 ||
        OP_TORQUE_MOVE !== 8'd8 || OP_TORQUE_OFF !== 8'd9)
      $fatal(1, "internal operation code mismatch");
    if (ADDR_CONTROL_MODE !== 8'h21 || ADDR_TORQUE_ENABLE !== 8'h28 ||
        ADDR_GOAL_ACCELERATION !== 8'h29 ||
        ADDR_GOAL_POSITION !== 8'h2a || ADDR_PWM_GOAL_SPEED !== 8'h2c ||
        ADDR_SPEED_GOAL !== 8'h2e || ADDR_PRESENT_POSITION !== 8'h38)
      $fatal(1, "register-table address mismatch");
    if (TORQUE_DISABLE !== 8'd0 || TORQUE_ENABLE !== 8'd1)
      $fatal(1, "torque switch value mismatch");
    $display("TB_HX30HM_PROTOCOL_PASS");
    $finish;
  end
endmodule
