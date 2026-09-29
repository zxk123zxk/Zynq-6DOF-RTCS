`timescale 1ns / 1ps

module tb_hx30hm_protocol;
  import hx30hm_protocol_pkg::*;

  initial begin
    // Golden vectors copied from the supplied HX-30HM protocol document.
    if (checksum_ping(8'h01) !== 8'hfb)
      $fatal(1, "PING checksum mismatch");
    if (checksum_read(8'h01, ADDR_PRESENT_POSITION, 8'h02) !== 8'hbe)
      $fatal(1, "READ position checksum mismatch");
    if (checksum_goal_position_write(8'h01, 16'h0800, 16'h0000, 16'h03e8) !== 8'hd5)
      $fatal(1, "goal-position WRITE checksum mismatch");
    if (ADDR_CONTROL_MODE !== 8'h21 || ADDR_TORQUE_ENABLE !== 8'h28 ||
        ADDR_GOAL_POSITION !== 8'h2a || ADDR_SPEED_GOAL !== 8'h2e ||
        ADDR_PRESENT_POSITION !== 8'h38)
      $fatal(1, "register-table address mismatch");
    $display("TB_HX30HM_PROTOCOL_PASS");
    $finish;
  end
endmodule
