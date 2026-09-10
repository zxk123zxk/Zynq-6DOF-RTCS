module safety_monitor (
  input logic clk, input logic rst_n, input logic estop_n,
  input logic watchdog_expired, input logic protocol_fault,
  output logic motion_permit, output logic fault_latched
);
  always_ff @(posedge clk) begin
    if (!rst_n || !estop_n) fault_latched <= 1'b1;
    else if (watchdog_expired || protocol_fault) fault_latched <= 1'b1;
  end
  assign motion_permit = estop_n && !fault_latched;
endmodule
