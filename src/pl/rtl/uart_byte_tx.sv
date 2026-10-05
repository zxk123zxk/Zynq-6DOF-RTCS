// One-byte 8N1 transmitter, 100 MHz / 100 = 1 Mbps.
module uart_byte_tx (
  input logic clk, rst_n, clear, start,
  input logic [7:0] data,
  output logic tx, busy, done
);
  logic [9:0] frame;
  logic [6:0] ticks;
  logic [3:0] bit_index;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx <= 1'b1;
      busy <= 1'b0;
      done <= 1'b0;
      frame <= '0;
      ticks <= '0;
      bit_index <= '0;
    end else if (clear) begin
      tx <= 1'b1;
      busy <= 1'b0;
      done <= 1'b0;
      frame <= '0;
      ticks <= '0;
      bit_index <= '0;
    end else begin
      done <= 1'b0;
      if (!busy) begin
        tx <= 1'b1;
        if (start) begin
          frame <= {1'b1, data, 1'b0};
          tx <= 1'b0;
          ticks <= 7'd99;
          bit_index <= 4'd0;
          busy <= 1'b1;
        end
      end else if (ticks != 0) begin
        ticks <= ticks - 1'b1;
      end else if (bit_index == 4'd9) begin
        tx <= 1'b1;
        busy <= 1'b0;
        done <= 1'b1;
      end else begin
        bit_index <= bit_index + 1'b1;
        tx <= frame[bit_index + 1'b1];
        ticks <= 7'd99;
      end
    end
  end
endmodule
