// HX-30HM 的 1 Mbps、8N1、半双工协议接口预留。
// 当前发送端始终禁用；在完成协议与电气验证前，不能将其作为真实物理层使用。
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
