// Single shared half-duplex engine: G1 PING/READ/torque-release and guarded G2 writes.
// Only rtcs_top may request a motion frame; the package pin has an independent inhibit.
module hx30hm_g1_engine #(
  parameter int unsigned RESPONSE_TIMEOUT_TICKS = 10_000_000
) (
  input logic clk, rst_n, clear, start,
  input logic [7:0] target_id, operation, // 1=PING, 2=READ position,
                                          // 8=torque+position, 9=torque off,
                                          // 11=READ torque switch
                                          // (no position-only opcode exists)
  input logic [15:0] write_position, write_speed, write_time,
  input logic [5:0][15:0] sync_position, sync_speed, sync_time,
  input logic rx,
  output logic tx, tx_enable, busy, done,
  output logic [3:0] fault_code,
  output logic [7:0] servo_error,
  output logic [15:0] position_raw
);
  import hx30hm_protocol_pkg::*;
  typedef enum logic [2:0] {IDLE, SEND, SEND_WAIT, TURN, RECEIVE} state_t;
  state_t state;
  logic [7:0] id_latched, op_latched;
  logic [15:0] position_latched, speed_latched, time_latched;
  logic [5:0] tx_index;
  logic [2:0] sync_axis_index;
  logic [3:0] sync_field_index;
  logic [3:0] rx_index;
  logic [5:0][15:0] sync_position_latched, sync_speed_latched, sync_time_latched;
  logic [7:0] tx_sum;
  logic [23:0] timeout_ticks;
  logic [7:0] sum;
  logic [7:0] tx_byte, rx_byte;
  logic tx_start, tx_busy, tx_done, rx_valid, rx_framing_fault;
  logic rx_flush;
  assign busy = state != IDLE;
  assign tx_enable = !clear && (state == SEND || state == SEND_WAIT);
  assign tx_start = state == SEND;
  // 半双工总线：发送期间接收机把本机发出的字节同样解成 rx_valid。若不冲刷，
  // 最后一个发送字节（当校验和恰为 0xFF 时尤其危险）会落在 RECEIVE 的
  // rx_index 0，被当成应答帧头，进而报出虚假的“应答ID不符”或校验和故障。
  // TURN 只持续一拍，在此复位接收状态机，丢弃自收残留，再从舵机起始位重新同步。
  assign rx_flush = (state == TURN);

  function automatic logic supported_op(input logic [7:0] op);
    begin
      supported_op = (op == OP_PING) || (op == OP_READ) ||
                     (op == OP_READ_TORQUE) ||
                     (op == OP_TORQUE_MOVE) || (op == OP_TORQUE_OFF) ||
                     (op == OP_SYNC_TORQUE_MOVE);
    end
  endfunction

  // 广播帧：FE, length=58, 83, 28, L=8, 六组(ID, torque, accel,
  // target, time, speed)。校验和在串行发送时逐字节累加，避免长组合链。
  // 广播没有应答，发送结束后必须逐轴 READ。

  // 每类操作的字节序列自成一段，避免下标 5/6 在不同长度帧里含义互相串位。
  always @* begin
    tx_byte = 8'h00;
    case (op_latched)
      OP_PING: case (tx_index)
        0, 1: tx_byte = FRAME_HEADER;
        2: tx_byte = id_latched;
        3: tx_byte = 8'd2;
        4: tx_byte = INST_PING;
        5: tx_byte = checksum_ping(id_latched);
        default: tx_byte = 8'h00;
      endcase
      OP_READ, OP_READ_TORQUE: case (tx_index)
        0, 1: tx_byte = FRAME_HEADER;
        2: tx_byte = id_latched;
        3: tx_byte = 8'd4;
        4: tx_byte = INST_READ;
        5: tx_byte = op_latched == OP_READ ? ADDR_PRESENT_POSITION : ADDR_TORQUE_ENABLE;
        6: tx_byte = op_latched == OP_READ ? 8'd2 : 8'd1;
        7: tx_byte = op_latched == OP_READ ?
          checksum_read(id_latched, ADDR_PRESENT_POSITION, 8'd2) :
          checksum_read(id_latched, ADDR_TORQUE_ENABLE, 8'd1);
        default: tx_byte = 8'h00;
      endcase
      // 运动帧：扭矩使能与目标位置在同一帧原子落地，不留下
      // “扭矩已开、目标仍是旧值”的窗口。
      OP_TORQUE_MOVE: case (tx_index)
        0, 1: tx_byte = FRAME_HEADER;
        2: tx_byte = id_latched;
        3: tx_byte = 8'h0b;
        4: tx_byte = INST_WRITE;
        5: tx_byte = ADDR_TORQUE_ENABLE;
        6: tx_byte = TORQUE_ENABLE;
        7: tx_byte = 8'd0;
        8: tx_byte = position_latched[7:0];
        9: tx_byte = position_latched[15:8];
        10: tx_byte = time_latched[7:0];
        11: tx_byte = time_latched[15:8];
        12: tx_byte = speed_latched[7:0];
        13: tx_byte = speed_latched[15:8];
        14: tx_byte = checksum_torque_move(id_latched, position_latched,
                                           time_latched, speed_latched);
        default: tx_byte = 8'h00;
      endcase
      // 卸力：0x28 <- 0，不产生位移，可重复发送。
      OP_TORQUE_OFF: case (tx_index)
        0, 1: tx_byte = FRAME_HEADER;
        2: tx_byte = id_latched;
        3: tx_byte = 8'd4;
        4: tx_byte = INST_WRITE;
        5: tx_byte = ADDR_TORQUE_ENABLE;
        6: tx_byte = TORQUE_DISABLE;
        7: tx_byte = checksum_torque_off(id_latched);
        default: tx_byte = 8'h00;
      endcase
      OP_SYNC_TORQUE_MOVE: begin : sync_frame
        case (tx_index)
          0, 1: tx_byte = FRAME_HEADER;
          2: tx_byte = BROADCAST_ID;
          3: tx_byte = 8'd58;
          4: tx_byte = INST_SYNC_WRITE;
          5: tx_byte = ADDR_TORQUE_ENABLE;
          6: tx_byte = 8'd8;
          61: tx_byte = ~tx_sum;
          default: begin
            case (sync_field_index)
              0: tx_byte = {5'd0, sync_axis_index} + 8'd1;
              1: tx_byte = TORQUE_ENABLE;
              2: tx_byte = 8'd0;
              3: tx_byte = sync_position_latched[sync_axis_index][7:0];
              4: tx_byte = sync_position_latched[sync_axis_index][15:8];
              5: tx_byte = sync_time_latched[sync_axis_index][7:0];
              6: tx_byte = sync_time_latched[sync_axis_index][15:8];
              7: tx_byte = sync_speed_latched[sync_axis_index][7:0];
              8: tx_byte = sync_speed_latched[sync_axis_index][15:8];
              default: tx_byte = 8'd0;
            endcase
          end
        endcase
      end
      default: tx_byte = 8'h00;
    endcase
  end

  uart_byte_tx u_tx (.clk(clk), .rst_n(rst_n), .clear(clear), .start(tx_start),
    .data(tx_byte), .tx(tx), .busy(tx_busy), .done(tx_done));
  uart_byte_rx u_rx (.clk(clk), .rst_n(rst_n), .clear(clear || rx_flush), .rx(rx),
    .data(rx_byte), .valid(rx_valid), .framing_fault(rx_framing_fault));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      id_latched <= '0;
      op_latched <= '0;
      position_latched <= '0;
      speed_latched <= '0;
      time_latched <= '0;
      sync_position_latched <= '0;
      sync_speed_latched <= '0;
      sync_time_latched <= '0;
      tx_index <= '0;
      sync_axis_index <= '0;
      sync_field_index <= '0;
      rx_index <= '0;
      timeout_ticks <= '0;
      sum <= '0;
      tx_sum <= '0;
      done <= 1'b0;
      fault_code <= '0;
      servo_error <= '0;
      position_raw <= '0;
    end else if (clear) begin
      state <= IDLE;
      tx_index <= '0;
      sync_axis_index <= '0;
      sync_field_index <= '0;
      rx_index <= '0;
      timeout_ticks <= '0;
      sum <= '0;
      tx_sum <= '0;
      done <= 1'b0;
      fault_code <= '0;
      servo_error <= '0;
      position_raw <= '0;
    end else begin
      case (state)
        IDLE: if (start) begin
          done <= 1'b0;
          fault_code <= '0;
          servo_error <= '0;
          position_raw <= '0;
          if (operation != OP_SYNC_TORQUE_MOVE &&
              (target_id == 0 || target_id >= BROADCAST_ID)) begin
            done <= 1'b1;
            fault_code <= 4'd1;
          end else if (!supported_op(operation)) begin
            done <= 1'b1;
            fault_code <= 4'd2;
          end else begin
            id_latched <= target_id;
            op_latched <= operation;
            position_latched <= write_position;
            speed_latched <= write_speed;
            time_latched <= write_time;
            sync_position_latched <= sync_position;
            sync_speed_latched <= sync_speed;
            sync_time_latched <= sync_time;
            tx_index <= '0;
            sync_axis_index <= '0;
            sync_field_index <= '0;
            tx_sum <= '0;
            state <= SEND;
          end
        end
        SEND: state <= SEND_WAIT;
        SEND_WAIT: if (tx_done) begin
          if (op_latched == OP_SYNC_TORQUE_MOVE && tx_index >= 6'd2 &&
              tx_index < LAST_INDEX_SYNC_TORQUE_MOVE)
            tx_sum <= tx_sum + tx_byte;
          if (op_latched == OP_SYNC_TORQUE_MOVE && tx_index >= 6'd7 &&
              tx_index < LAST_INDEX_SYNC_TORQUE_MOVE) begin
            if (sync_field_index == 4'd8) begin
              sync_field_index <= 0;
              sync_axis_index <= sync_axis_index + 1'b1;
            end else sync_field_index <= sync_field_index + 1'b1;
          end
          if (tx_index == last_tx_index(op_latched)) begin
            if (op_latched == OP_SYNC_TORQUE_MOVE) begin
              done <= 1'b1;
              state <= IDLE;
            end else state <= TURN;
          end
          else begin
            tx_index <= tx_index + 1'b1;
            state <= SEND;
          end
        end
        TURN: begin
          rx_index <= '0;
          timeout_ticks <= '0;
          sum <= '0;
          state <= RECEIVE;
        end
        RECEIVE: begin
          if (rx_framing_fault) begin
            fault_code <= 4'd5;
            done <= 1'b1;
            state <= IDLE;
          end else if (timeout_ticks >= RESPONSE_TIMEOUT_TICKS - 1) begin
            fault_code <= 4'd3;
            done <= 1'b1;
            state <= IDLE;
          end else begin
            timeout_ticks <= timeout_ticks + 1'b1;
            if (rx_valid) begin
              case (rx_index)
                0: if (rx_byte == FRAME_HEADER) rx_index <= 1;
                1: rx_index <= rx_byte == FRAME_HEADER ? 4'd2 : 4'd0;
                2: if (rx_byte != id_latched) begin
                     fault_code <= 4'd6; done <= 1'b1; state <= IDLE;
                   end else begin sum <= rx_byte; rx_index <= 3; end
                3: if (rx_byte != (op_latched == OP_READ ? 8'd4 :
                                   op_latched == OP_READ_TORQUE ? 8'd3 : 8'd2)) begin
                     fault_code <= 4'd4; done <= 1'b1; state <= IDLE;
                   end else begin sum <= sum + rx_byte; rx_index <= 4; end
                4: begin servo_error <= rx_byte; sum <= sum + rx_byte; rx_index <= 5; end
                5: if (op_latched != OP_READ && op_latched != OP_READ_TORQUE) begin
                     fault_code <= rx_byte != ~sum ? 4'd7 :
                                   servo_error != 0 ? 4'd8 : 4'd0;
                     done <= 1'b1; state <= IDLE;
                   end else begin
                     position_raw[7:0] <= rx_byte;
                     sum <= sum + rx_byte;
                     rx_index <= 6;
                   end
                6: if (op_latched == OP_READ_TORQUE) begin
                     fault_code <= rx_byte != ~sum ? 4'd7 :
                                   servo_error != 0 ? 4'd8 : 4'd0;
                     done <= 1'b1; state <= IDLE;
                   end else begin
                     position_raw[15:8] <= rx_byte;
                     sum <= sum + rx_byte;
                     rx_index <= 7;
                   end
                7: begin
                     fault_code <= rx_byte != ~sum ? 4'd7 :
                                   servo_error != 0 ? 4'd8 : 4'd0;
                     done <= 1'b1; state <= IDLE;
                   end
                default: begin fault_code <= 4'd4; done <= 1'b1; state <= IDLE; end
              endcase
            end
          end
        end
        default: state <= IDLE;
      endcase
    end
  end
endmodule
