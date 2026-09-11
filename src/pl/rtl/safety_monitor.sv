module safety_monitor (
  input logic clk, input logic rst_n, input logic estop_n,
  input logic watchdog_expired, input logic protocol_fault,
  output logic motion_permit, output logic fault_latched
);
  // 急停、看门狗超时或协议故障都会锁存故障；复位前不允许恢复运动许可。
  always_ff @(posedge clk) begin
    if (!rst_n || !estop_n) fault_latched <= 1'b1;
    else if (watchdog_expired || protocol_fault) fault_latched <= 1'b1;
  end
  // 急停为低有效，且必须同时没有锁存故障才可允许运动。
  assign motion_permit = estop_n && !fault_latched;
endmodule
