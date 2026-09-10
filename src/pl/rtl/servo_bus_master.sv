// Interface reservation for the HX-30HM 1 Mbps, 8N1, half-duplex protocol.
// TX remains disabled; this module must never be used as an active PHY yet.
module servo_bus_master (
  input logic clk, input logic rst_n, input logic rx,
  output logic tx, output logic tx_enable, output logic protocol_fault
);
  always_comb begin
    tx = 1'b1;
    tx_enable = 1'b0;
    protocol_fault = 1'b0;
  end
endmodule
