module axi_lite_regs #(
  parameter int unsigned AXIS_COUNT = 6
) (
  input logic clk, input logic rst_n,
  input logic [31:0] s_axi_awaddr, input logic s_axi_awvalid, output logic s_axi_awready,
  input logic [31:0] s_axi_wdata, input logic [3:0] s_axi_wstrb, input logic s_axi_wvalid, output logic s_axi_wready,
  output logic [1:0] s_axi_bresp, output logic s_axi_bvalid, input logic s_axi_bready,
  input logic [31:0] s_axi_araddr, input logic s_axi_arvalid, output logic s_axi_arready,
  output logic [31:0] s_axi_rdata, output logic [1:0] s_axi_rresp, output logic s_axi_rvalid, input logic s_axi_rready,
  input logic [63:0] hw_ticks, output logic [31:0] control, output logic [31:0] command,
  input logic [31:0] status, input logic [31:0] irq_status,
  output logic [31:0] target [0:AXIS_COUNT-1], output logic [31:0] profile_speed,
  output logic [31:0] profile_accel, output logic [63:0] deadline,
  output logic [31:0] servo_config
);
  import rtcs_pkg::*;
  logic [31:0] awaddr_q, wdata_q;
  logic [3:0] wstrb_q;
  logic aw_hold, w_hold;
  integer i;

  // 根据 AXI 写选通掩码合并字节，避免部分写误覆盖同一寄存器的其他字节。
  function automatic logic [31:0] merge_bytes(
    input logic [31:0] prior, input logic [31:0] incoming, input logic [3:0] strobe
  );
    integer byte_index;
    begin
      merge_bytes = prior;
      for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
        if (strobe[byte_index]) merge_bytes[byte_index*8 +: 8] = incoming[byte_index*8 +: 8];
    end
  endfunction

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      aw_hold <= 1'b0; w_hold <= 1'b0; s_axi_bvalid <= 1'b0;
      control <= '0; command <= '0; profile_speed <= '0; profile_accel <= '0; deadline <= '0; servo_config <= '0;
      for (i = 0; i < AXIS_COUNT; i = i + 1) target[i] <= '0;
    end else begin
      if (s_axi_awvalid && s_axi_awready) begin awaddr_q <= s_axi_awaddr; aw_hold <= 1'b1; end
      if (s_axi_wvalid && s_axi_wready) begin
        wdata_q <= s_axi_wdata;
        wstrb_q <= s_axi_wstrb;
        w_hold <= 1'b1;
      end
      // AXI 地址和数据可在不同周期到达；两者齐全后才提交一次写事务。
      if (aw_hold && w_hold && !s_axi_bvalid) begin
        unique case (awaddr_q[7:0])
          REG_CONTROL: control <= merge_bytes(control, wdata_q, wstrb_q);
          REG_COMMAND: command <= merge_bytes(command, wdata_q, wstrb_q);
          REG_PROFILE_SPEED: profile_speed <= merge_bytes(profile_speed, wdata_q, wstrb_q);
          REG_PROFILE_ACCEL: profile_accel <= merge_bytes(profile_accel, wdata_q, wstrb_q);
          REG_DEADLINE_LO: deadline[31:0] <= merge_bytes(deadline[31:0], wdata_q, wstrb_q);
          REG_DEADLINE_HI: deadline[63:32] <= merge_bytes(deadline[63:32], wdata_q, wstrb_q);
          REG_SERVO_CONFIG: servo_config <= merge_bytes(servo_config, wdata_q, wstrb_q);
          default: begin
            for (i = 0; i < AXIS_COUNT; i = i + 1)
              if (awaddr_q[7:0] == (REG_TARGET0 + (i * 4)))
                target[i] <= merge_bytes(target[i], wdata_q, wstrb_q);
          end
        endcase
        aw_hold <= 1'b0; w_hold <= 1'b0; s_axi_bvalid <= 1'b1;
      end
      if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
    end
  end

  assign s_axi_awready = rst_n && !aw_hold && !s_axi_bvalid;
  assign s_axi_wready  = rst_n && !w_hold  && !s_axi_bvalid;
  assign s_axi_bresp   = 2'b00;

  always_ff @(posedge clk) begin
    if (!rst_n) begin s_axi_rvalid <= 1'b0; s_axi_rdata <= '0; end
    else begin
      if (s_axi_arvalid && s_axi_arready) begin
        s_axi_rvalid <= 1'b1;
        // 读地址握手后锁存返回数据，直到主机完成 R 通道握手。
        unique case (s_axi_araddr[7:0])
          REG_ID_VERSION: s_axi_rdata <= ID_VERSION;
          REG_CONTROL: s_axi_rdata <= control;
          REG_COMMAND: s_axi_rdata <= command;
          REG_STATUS: s_axi_rdata <= status;
          REG_IRQ_STATUS: s_axi_rdata <= irq_status;
          REG_TICKS_LO: s_axi_rdata <= hw_ticks[31:0];
          REG_TICKS_HI: s_axi_rdata <= hw_ticks[63:32];
          REG_PROFILE_SPEED: s_axi_rdata <= profile_speed;
          REG_PROFILE_ACCEL: s_axi_rdata <= profile_accel;
          REG_DEADLINE_LO: s_axi_rdata <= deadline[31:0];
          REG_DEADLINE_HI: s_axi_rdata <= deadline[63:32];
          REG_SERVO_CONFIG: s_axi_rdata <= servo_config;
          default: begin
            s_axi_rdata <= 32'd0;
            for (i = 0; i < AXIS_COUNT; i = i + 1)
              if (s_axi_araddr[7:0] == (REG_TARGET0 + (i * 4))) s_axi_rdata <= target[i];
          end
        endcase
      end else if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
    end
  end
  assign s_axi_arready = rst_n && !s_axi_rvalid;
  assign s_axi_rresp = 2'b00;
endmodule
