`ifndef RTCS_PKG_SV
`define RTCS_PKG_SV
package rtcs_pkg;
  parameter int unsigned AXIS_COUNT = 6;
  parameter logic [31:0] ID_VERSION = 32'h5254_0001;

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
endpackage
`endif
