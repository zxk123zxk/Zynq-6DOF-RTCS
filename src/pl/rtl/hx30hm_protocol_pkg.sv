`ifndef HX30HM_PROTOCOL_PKG_SV
`define HX30HM_PROTOCOL_PKG_SV

// HX-30HM protocol constants and checksum helpers.
// This package contains no state and cannot drive a physical bus. The UART
// transmitter may use these helpers only after the G1 PHY/safety gate is met.
package hx30hm_protocol_pkg;
  localparam logic [7:0] FRAME_HEADER = 8'hff;
  localparam logic [7:0] BROADCAST_ID = 8'hfe;

  localparam logic [7:0] INST_PING       = 8'h01;
  localparam logic [7:0] INST_READ       = 8'h02;
  localparam logic [7:0] INST_WRITE      = 8'h03;
  localparam logic [7:0] INST_REG_WRITE  = 8'h04;
  localparam logic [7:0] INST_ACTION     = 8'h05;
  localparam logic [7:0] INST_RESET      = 8'h06;
  localparam logic [7:0] INST_SYNC_READ  = 8'h82;
  localparam logic [7:0] INST_SYNC_WRITE = 8'h83;

  localparam logic [7:0] ADDR_GOAL_POSITION = 8'h2a;
  localparam logic [7:0] ADDR_CONTROL_MODE = 8'h21;
  localparam logic [7:0] ADDR_TORQUE_ENABLE = 8'h28;
  localparam logic [7:0] ADDR_GOAL_ACCELERATION = 8'h29;
  localparam logic [7:0] ADDR_PWM_GOAL_SPEED = 8'h2c;
  localparam logic [7:0] ADDR_SPEED_GOAL = 8'h2e;
  localparam logic [7:0] ADDR_PRESENT_POSITION = 8'h38;

  localparam logic [7:0] CONTROL_MODE_POSITION = 8'd0;
  localparam logic [7:0] CONTROL_MODE_SPEED = 8'd1;
  localparam logic [7:0] CONTROL_MODE_PWM_SPEED = 8'd2;
  localparam logic [7:0] TORQUE_DISABLE = 8'd0;
  localparam logic [7:0] TORQUE_ENABLE = 8'd1;

  function automatic logic [7:0] checksum_ping(input logic [7:0] id);
    logic [7:0] sum;
    begin
      sum = id + 8'd2 + INST_PING;
      checksum_ping = ~sum;
    end
  endfunction

  function automatic logic [7:0] checksum_read(
    input logic [7:0] id,
    input logic [7:0] start_address,
    input logic [7:0] read_length
  );
    logic [7:0] sum;
    begin
      sum = id + 8'd4 + INST_READ + start_address + read_length;
      checksum_read = ~sum;
    end
  endfunction

  // Computes the checksum for a WRITE beginning at 0x2a with the documented
  // six-byte payload: position, time and speed, all little-endian.
  function automatic logic [7:0] checksum_goal_position_write(
    input logic [7:0] id,
    input logic [15:0] position,
    input logic [15:0] time_value,
    input logic [15:0] speed
  );
    logic [7:0] sum;
    begin
      sum = id + 8'd9 + INST_WRITE + ADDR_GOAL_POSITION +
            position[7:0] + position[15:8] +
            time_value[7:0] + time_value[15:8] +
            speed[7:0] + speed[15:8];
      checksum_goal_position_write = ~sum;
    end
  endfunction
endpackage
`endif
