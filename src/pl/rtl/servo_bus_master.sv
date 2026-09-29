// Receive-only 1 Mbps 8N1 preparation at the 100 MHz PS FCLK0 rate.
// The transmit path remains structurally disabled. This module does not parse
// or send HX-30HM commands; physical RX wiring is a later hardware gate.
module servo_bus_master (
  input logic clk, input logic rst_n, input logic rx,
  output logic tx, output logic tx_enable, output logic protocol_fault,
  output logic [7:0] observed_byte, output logic observed_valid
);
  localparam int CLOCKS_PER_BIT = 100;
  typedef enum logic [1:0] {IDLE, START, DATA, STOP} rx_state_t;
  rx_state_t state;
  logic rx_meta, rx_sync;
  logic [6:0] bit_timer;
  logic [2:0] bit_index;
  logic [7:0] shift_byte;

  assign tx = 1'b1;
  assign tx_enable = 1'b0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rx_meta <= 1'b1;
      rx_sync <= 1'b1;
    end else begin
      rx_meta <= rx;
      rx_sync <= rx_meta;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      bit_timer <= '0;
      bit_index <= '0;
      shift_byte <= '0;
      observed_byte <= '0;
      observed_valid <= 1'b0;
      protocol_fault <= 1'b0;
    end else begin
      observed_valid <= 1'b0;
      case (state)
        IDLE: if (!rx_sync) begin
          bit_timer <= CLOCKS_PER_BIT / 2 - 1;
          state <= START;
        end
        START: if (bit_timer != 0) bit_timer <= bit_timer - 1'b1;
        else if (rx_sync) state <= IDLE;
        else begin
          bit_timer <= CLOCKS_PER_BIT - 1;
          bit_index <= '0;
          state <= DATA;
        end
        DATA: if (bit_timer != 0) bit_timer <= bit_timer - 1'b1;
        else begin
          shift_byte[bit_index] <= rx_sync;
          bit_timer <= CLOCKS_PER_BIT - 1;
          if (bit_index == 3'd7) state <= STOP;
          else bit_index <= bit_index + 1'b1;
        end
        STOP: if (bit_timer != 0) bit_timer <= bit_timer - 1'b1;
        else begin
          if (rx_sync) begin
            observed_byte <= shift_byte;
            observed_valid <= 1'b1;
          end else protocol_fault <= 1'b1;
          state <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end
endmodule
