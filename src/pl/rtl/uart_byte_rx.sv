// Synchronised 1 Mbps 8N1 receiver. A bad stop bit raises a one-cycle fault.
module uart_byte_rx (
  input logic clk, rst_n, clear, rx,
  output logic [7:0] data,
  output logic valid, framing_fault
);
  typedef enum logic [1:0] {IDLE, START, BITS, STOP} state_t;
  state_t state;
  logic rx_meta, rx_sync;
  logic [6:0] ticks;
  logic [2:0] bit_index;
  logic [7:0] shift;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rx_meta <= 1'b1;
      rx_sync <= 1'b1;
    end else if (clear) begin
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
      ticks <= '0;
      bit_index <= '0;
      shift <= '0;
      data <= '0;
      valid <= 1'b0;
      framing_fault <= 1'b0;
    end else if (clear) begin
      state <= IDLE;
      ticks <= '0;
      bit_index <= '0;
      shift <= '0;
      data <= '0;
      valid <= 1'b0;
      framing_fault <= 1'b0;
    end else begin
      valid <= 1'b0;
      framing_fault <= 1'b0;
      case (state)
        IDLE: if (!rx_sync) begin ticks <= 7'd49; state <= START; end
        START: if (ticks != 0) ticks <= ticks - 1'b1;
               else if (rx_sync) state <= IDLE;
               else begin ticks <= 7'd99; bit_index <= '0; state <= BITS; end
        BITS: if (ticks != 0) ticks <= ticks - 1'b1;
              else begin
                shift[bit_index] <= rx_sync;
                ticks <= 7'd99;
                if (bit_index == 3'd7) state <= STOP;
                else bit_index <= bit_index + 1'b1;
              end
        STOP: if (ticks != 0) ticks <= ticks - 1'b1;
              else begin
                if (rx_sync) begin data <= shift; valid <= 1'b1; end
                else framing_fault <= 1'b1;
                state <= IDLE;
              end
        default: state <= IDLE;
      endcase
    end
  end
endmodule
