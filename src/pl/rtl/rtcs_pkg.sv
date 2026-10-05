`ifndef RTCS_PKG_SV
`define RTCS_PKG_SV
package rtcs_pkg;
  // 系统固定为六关节；PS 与 PL 必须使用相同的轴数量。
  parameter int unsigned AXIS_COUNT = 6;
  // 供软件启动时确认已连接到兼容版本的 PL 外设。
  parameter logic [31:0] ID_VERSION = 32'h5254_0003;

  // AXI4-Lite 寄存器字节偏移：与 PS 端 rtcs_registers.hpp 保持一致。
  localparam logic [7:0] REG_ID_VERSION    = 8'h00;
  localparam logic [7:0] REG_CONTROL       = 8'h04;
  localparam logic [7:0] REG_COMMAND       = 8'h08;
  localparam logic [7:0] REG_STATUS        = 8'h0c;
  localparam logic [7:0] REG_IRQ_STATUS    = 8'h10;
  localparam logic [7:0] REG_TICKS_LO      = 8'h14;
  localparam logic [7:0] REG_TICKS_HI      = 8'h18;
  localparam logic [7:0] REG_TARGET0       = 8'h20;
  localparam logic [7:0] REG_PROFILE_SPEED = 8'h38;
  localparam logic [7:0] REG_PROFILE_ACCEL = 8'h3c;
  localparam logic [7:0] REG_DEADLINE_LO   = 8'h40;
  localparam logic [7:0] REG_DEADLINE_HI   = 8'h44;
  localparam logic [7:0] REG_SERVO_CONFIG  = 8'h48;
  localparam logic [7:0] REG_DEBUG         = 8'h4c;
  localparam logic [7:0] REG_G1_ID         = 8'h50;
  localparam logic [7:0] REG_G1_OP         = 8'h54;
  localparam logic [7:0] REG_G1_CMD        = 8'h58;
  localparam logic [7:0] REG_G1_STATUS     = 8'h5c;
  localparam logic [7:0] REG_G1_RESULT     = 8'h60;
  localparam logic [7:0] REG_G1_FAULT      = 8'h64;
endpackage
`endif
