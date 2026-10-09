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

  // 引擎内部操作码（PS 写 G1_OP，或由 rtcs_top 的 G2 状态机驱动）。
  // 0x28 扭矩开关在 SRAM、上电初始值为 0，即出厂状态卸力：只写 0x2A 目标位置
  // 会得到“应答 ERROR=0 但不出力”。因此运动帧把扭矩与目标位置写成同一帧。
  // 8/9 在总线上仍编码为 INST_WRITE：0x04 是 REG_WRITE（要等 ACTION 才生效）、
  // 0x05 是 ACTION，都不能拿来当写指令用。
  // 这里不实现“只写 0x2A”的旧帧：没有任何路径需要它，留着只会多一条绕过
  // 扭矩使能、单独写位置的分支。旧帧的实物证据保留在归档说明里。
  localparam logic [7:0] OP_PING = 8'd1;
  localparam logic [7:0] OP_READ = 8'd2;
  localparam logic [7:0] OP_TORQUE_MOVE = 8'd8;
  localparam logic [7:0] OP_TORQUE_OFF = 8'd9;
  localparam logic [7:0] OP_SYNC_TORQUE_MOVE = 8'd10;
  localparam logic [7:0] OP_READ_TORQUE = 8'd11;

  localparam logic [5:0] LAST_INDEX_PING = 6'd5;
  localparam logic [5:0] LAST_INDEX_READ = 6'd7;
  localparam logic [5:0] LAST_INDEX_TORQUE_MOVE = 6'd14;
  localparam logic [5:0] LAST_INDEX_TORQUE_OFF = 6'd7;
  localparam logic [5:0] LAST_INDEX_SYNC_TORQUE_MOVE = 6'd61;

  // 帧内最后的发送下标随内部操作码变化，引擎不得用固定的字节数假设。
  function automatic logic [5:0] last_tx_index(input logic [7:0] op);
    begin
      unique case (op)
        OP_PING: last_tx_index = LAST_INDEX_PING;
        OP_READ, OP_READ_TORQUE: last_tx_index = LAST_INDEX_READ;
        OP_TORQUE_MOVE: last_tx_index = LAST_INDEX_TORQUE_MOVE;
        OP_TORQUE_OFF: last_tx_index = LAST_INDEX_TORQUE_OFF;
        OP_SYNC_TORQUE_MOVE: last_tx_index = LAST_INDEX_SYNC_TORQUE_MOVE;
        default: last_tx_index = LAST_INDEX_PING;
      endcase
    end
  endfunction

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

  // 从 0x28 起连续八字节的受限运动帧，一次原子落地：
  //   0x28 扭矩开关=1、0x29 加速度=0、0x2A 目标位置(2B)、0x2C 原始时间(2B)、0x2E 原始速度(2B)。
  // 长度字段 = 2 + 1 起始地址 + 8 数据 = 11 (0x0B)。
  function automatic logic [7:0] checksum_torque_move(
    input logic [7:0] id,
    input logic [15:0] position,
    input logic [15:0] time_raw,
    input logic [15:0] speed
  );
    logic [7:0] sum;
    begin
      sum = id + 8'd11 + INST_WRITE + ADDR_TORQUE_ENABLE + TORQUE_ENABLE + 8'd0 +
            position[7:0] + position[15:8] + time_raw[7:0] + time_raw[15:8] +
            speed[7:0] + speed[15:8];
      checksum_torque_move = ~sum;
    end
  endfunction

  // 只卸力的单字节写：0x28 <- 0。长度字段 = 2 + 1 + 1 = 4。
  function automatic logic [7:0] checksum_torque_off(input logic [7:0] id);
    logic [7:0] sum;
    begin
      sum = id + 8'd4 + INST_WRITE + ADDR_TORQUE_ENABLE + TORQUE_DISABLE;
      checksum_torque_off = ~sum;
    end
  endfunction
endpackage
`endif
