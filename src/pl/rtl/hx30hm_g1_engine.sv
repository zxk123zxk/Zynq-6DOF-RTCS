// G1 single-cast read-only bus engine. Physical TX is controlled by the
// selected BD wrapper and its independent pulled-up inhibit input.
module hx30hm_g1_engine #(
  parameter int unsigned RESPONSE_TIMEOUT_TICKS = 10_000_000
) (
  input logic clk, rst_n, clear, start,
  input logic [7:0] target_id, operation, // 1=PING, 2=READ position
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
  logic [3:0] tx_index, rx_index;
  logic [23:0] timeout_ticks;
  logic [7:0] sum;
  logic [7:0] tx_byte, rx_byte;
  logic tx_start, tx_busy, tx_done, rx_valid, rx_framing_fault;
  assign busy = state != IDLE;
  assign tx_enable = !clear && (state == SEND || state == SEND_WAIT);
  assign tx_start = state == SEND;

  always_comb begin
    tx_byte = 8'h00;
    case (tx_index)
      0, 1: tx_byte = FRAME_HEADER;
      2: tx_byte = id_latched;
      3: tx_byte = op_latched == INST_PING ? 8'd2 : 8'd4;
      4: tx_byte = op_latched;
      5: tx_byte = op_latched == INST_PING ? checksum_ping(id_latched) : ADDR_PRESENT_POSITION;
      6: tx_byte = 8'd2;
      7: tx_byte = checksum_read(id_latched, ADDR_PRESENT_POSITION, 8'd2);
      default: tx_byte = 8'h00;
    endcase
  end

  uart_byte_tx u_tx (.clk(clk), .rst_n(rst_n), .clear(clear), .start(tx_start),
    .data(tx_byte), .tx(tx), .busy(tx_busy), .done(tx_done));
  uart_byte_rx u_rx (.clk(clk), .rst_n(rst_n), .clear(clear), .rx(rx),
    .data(rx_byte), .valid(rx_valid), .framing_fault(rx_framing_fault));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      id_latched <= '0;
      op_latched <= '0;
      tx_index <= '0;
      rx_index <= '0;
      timeout_ticks <= '0;
      sum <= '0;
      done <= 1'b0;
      fault_code <= '0;
      servo_error <= '0;
      position_raw <= '0;
    end else if (clear) begin
      state <= IDLE;
      tx_index <= '0;
      rx_index <= '0;
      timeout_ticks <= '0;
      sum <= '0;
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
          if (target_id == 0 || target_id >= BROADCAST_ID) begin
            done <= 1'b1;
            fault_code <= 4'd1;
          end else if (operation != INST_PING && operation != INST_READ) begin
            done <= 1'b1;
            fault_code <= 4'd2;
          end else begin
            id_latched <= target_id;
            op_latched <= operation;
            tx_index <= '0;
            state <= SEND;
          end
        end
        SEND: state <= SEND_WAIT;
        SEND_WAIT: if (tx_done) begin
          if (tx_index == (op_latched == INST_PING ? 4'd5 : 4'd7))
            state <= TURN;
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
                3: if (rx_byte != (op_latched == INST_PING ? 8'd2 : 8'd4)) begin
                     fault_code <= 4'd4; done <= 1'b1; state <= IDLE;
                   end else begin sum <= sum + rx_byte; rx_index <= 4; end
                4: begin servo_error <= rx_byte; sum <= sum + rx_byte; rx_index <= 5; end
                5: if (op_latched == INST_PING) begin
                     fault_code <= rx_byte != ~sum ? 4'd7 :
                                   servo_error != 0 ? 4'd8 : 4'd0;
                     done <= 1'b1; state <= IDLE;
                   end else begin
                     position_raw[7:0] <= rx_byte;
                     sum <= sum + rx_byte;
                     rx_index <= 6;
                   end
                6: begin
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
