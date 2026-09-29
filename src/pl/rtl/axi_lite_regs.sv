// AXI4-Lite register bank for the RTCS control plane.
//
// This module follows the teaching-oriented structure of axi_temple.sv:
//   AW address buffer + W data buffer -> B response
//   AR address buffer                 -> R response
// The RTCS version retains WSTRB, AXI response codes, and the full six-axis
// register map required by the PS/PL contract.
module axi_lite_regs #(
  parameter int unsigned AXI_ADDR_WIDTH = 8,
  parameter int unsigned AXIS_COUNT = 6
) (
  // 时钟与复位；AXI 复位为低有效。
  input  logic                      aclk,
  input  logic                      aresetn,

  // AXI4-Lite 写地址通道（AW）。
  input  logic [AXI_ADDR_WIDTH-1:0] saxi_awaddr,
  input  logic                      saxi_awvalid,
  output logic                      saxi_awready,

  // AXI4-Lite 读地址通道（AR）。
  input  logic [AXI_ADDR_WIDTH-1:0] saxi_araddr,
  input  logic                      saxi_arvalid,
  output logic                      saxi_arready,

  // AXI4-Lite 写数据通道（W）。
  output logic                      saxi_wready,
  input  logic                      saxi_wvalid,
  input  logic [31:0]               saxi_wdata,
  input  logic [3:0]                saxi_wstrb,

  // AXI4-Lite 读数据通道（R）。
  input  logic                      saxi_rready,
  output logic                      saxi_rvalid,
  output logic [31:0]               saxi_rdata,
  output logic [1:0]                saxi_rresp,

  // AXI4-Lite 写响应通道（B）。
  input  logic                      saxi_bready,
  output logic                      saxi_bvalid,
  output logic [1:0]                saxi_bresp,

  // 只读的顶层状态输入。
  input  logic [63:0]               hw_ticks,
  input  logic [31:0]               status,
  input  logic [31:0]               irq_status,

  // PS 写入、后续运动模块读取的控制寄存器。
  output logic [31:0]               control,
  output logic [31:0]               command,
  output logic [31:0]               target [0:AXIS_COUNT-1],
  output logic [31:0]               profile_speed,
  output logic [31:0]               profile_accel,
  output logic [63:0]               deadline,
  output logic [31:0]               servo_config
);
  import rtcs_pkg::*;

  //============================================================
  // AXI register storage
  //============================================================
  logic [31:0] control_reg;
  logic [31:0] command_reg;
  logic [31:0] target_reg [0:AXIS_COUNT-1];
  logic [31:0] profile_speed_reg;
  logic [31:0] profile_accel_reg;
  logic [63:0] deadline_reg;
  logic [31:0] servo_config_reg;
  integer read_axis_index;
  integer write_axis_index;

  assign control       = control_reg;
  assign command       = command_reg;
  assign profile_speed = profile_speed_reg;
  assign profile_accel = profile_accel_reg;
  assign deadline      = deadline_reg;
  assign servo_config  = servo_config_reg;

  generate
    for (genvar axis = 0; axis < AXIS_COUNT; axis = axis + 1) begin : g_target_outputs
      assign target[axis] = target_reg[axis];
    end
  endgenerate

  // 根据 WSTRB 合并有效字节，未选中的字节保持原寄存器值。
  function automatic logic [31:0] merge_write_bytes(
    input logic [31:0] prior,
    input logic [31:0] incoming,
    input logic [3:0]  strobe
  );
    integer byte_index;
    begin
      merge_write_bytes = prior;
      for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1) begin
        if (strobe[byte_index])
          merge_write_bytes[byte_index*8 +: 8] = incoming[byte_index*8 +: 8];
      end
    end
  endfunction

  //============================================================
  // Write channel: AW address buffer + W data buffer -> B response
  //============================================================

  // AW address buffer
  logic [AXI_ADDR_WIDTH-1:0] axi_awaddr_buffer;
  logic                      axi_awaddr_valid;

  // W data buffer
  logic [31:0] axi_wdata_buffer;
  logic [3:0]  axi_wstrb_buffer;
  logic        axi_wdata_valid;

  // A committed write uses the buffered address and data, never live inputs.
  logic [AXI_ADDR_WIDTH-1:0] axi_waddr;
  logic                      axi_need_write_response;

  // 当前未缓存 AW 地址且未等待 B 响应时，可接收新的写地址。
  always_comb begin
    if (aresetn && !axi_awaddr_valid && !saxi_bvalid)
      saxi_awready = 1'b1;
    else
      saxi_awready = 1'b0;
  end

  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      axi_awaddr_buffer <= '0;
      axi_awaddr_valid  <= 1'b0;
    end else begin
      if (saxi_awvalid && saxi_awready) begin
        axi_awaddr_buffer <= saxi_awaddr;
        axi_awaddr_valid  <= 1'b1;
      end else if (axi_need_write_response) begin
        axi_awaddr_valid <= 1'b0;
      end
    end
  end

  // 当前未缓存 W 数据且未等待 B 响应时，可接收新的写数据。
  always_comb begin
    if (aresetn && !axi_wdata_valid && !saxi_bvalid)
      saxi_wready = 1'b1;
    else
      saxi_wready = 1'b0;
  end

  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      axi_wdata_buffer <= '0;
      axi_wstrb_buffer <= '0;
      axi_wdata_valid  <= 1'b0;
    end else begin
      if (saxi_wvalid && saxi_wready) begin
        axi_wdata_buffer <= saxi_wdata;
        axi_wstrb_buffer <= saxi_wstrb;
        axi_wdata_valid  <= 1'b1;
      end else if (axi_need_write_response) begin
        axi_wdata_valid <= 1'b0;
      end
    end
  end

  always_comb begin
    axi_waddr = axi_awaddr_buffer;
    axi_need_write_response = axi_awaddr_valid && axi_wdata_valid && !saxi_bvalid;
  end

  // AW 和 W 都到达后产生一次 OKAY 写响应，并保持到 BREADY 握手。
  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      saxi_bvalid <= 1'b0;
    end else begin
      if (axi_need_write_response)
        saxi_bvalid <= 1'b1;
      else if (saxi_bvalid && saxi_bready)
        saxi_bvalid <= 1'b0;
    end
  end

  assign saxi_bresp = 2'b00;  // OKAY

  //============================================================
  // Read channel: AR address buffer -> R response
  //============================================================

  logic [AXI_ADDR_WIDTH-1:0] axi_raddr;
  logic                      axi_need_read;
  logic [31:0]               axi_data_to_read;

  // 未保存 AR 地址且没有待主机接收的 R 数据时，可接收新的读地址。
  always_comb begin
    if (aresetn && !axi_need_read && !saxi_rvalid)
      saxi_arready = 1'b1;
    else
      saxi_arready = 1'b0;
  end

  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      axi_raddr     <= '0;
      axi_need_read <= 1'b0;
    end else begin
      if (saxi_arvalid && saxi_arready) begin
        axi_raddr     <= saxi_araddr;
        axi_need_read <= 1'b1;
      end else begin
        axi_need_read <= 1'b0;
      end
    end
  end

  // 根据已缓存的读地址选择寄存器；未知地址读取零。
  always_comb begin
    unique case (axi_raddr)
      REG_ID_VERSION:    axi_data_to_read = ID_VERSION;
      REG_CONTROL:       axi_data_to_read = control_reg;
      REG_COMMAND:       axi_data_to_read = command_reg;
      REG_STATUS:        axi_data_to_read = status;
      REG_IRQ_STATUS:    axi_data_to_read = irq_status;
      REG_TICKS_LO:      axi_data_to_read = hw_ticks[31:0];
      REG_TICKS_HI:      axi_data_to_read = hw_ticks[63:32];
      REG_PROFILE_SPEED: axi_data_to_read = profile_speed_reg;
      REG_PROFILE_ACCEL: axi_data_to_read = profile_accel_reg;
      REG_DEADLINE_LO:   axi_data_to_read = deadline_reg[31:0];
      REG_DEADLINE_HI:   axi_data_to_read = deadline_reg[63:32];
      REG_SERVO_CONFIG:  axi_data_to_read = servo_config_reg;
      default: begin
        axi_data_to_read = 32'b0;
        for (read_axis_index = 0; read_axis_index < AXIS_COUNT; read_axis_index = read_axis_index + 1) begin
          if (axi_raddr == (REG_TARGET0 + (read_axis_index * 4)))
            axi_data_to_read = target_reg[read_axis_index];
        end
      end
    endcase
  end

  // 收到 AR 后锁存 RDATA 并置 RVALID；RVALID 保持到 RREADY 握手。
  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      saxi_rvalid <= 1'b0;
      saxi_rdata  <= 32'b0;
    end else begin
      if (axi_need_read) begin
        saxi_rdata  <= axi_data_to_read;
        saxi_rvalid <= 1'b1;
      end
      else if (saxi_rvalid && saxi_rready) begin
        saxi_rvalid <= 1'b0;
      end
    end
  end

  assign saxi_rresp = 2'b00;  // OKAY

  //============================================================
  // AXI register writes
  //============================================================

  // 只有 AW 和 W 都已握手缓存后才写寄存器；没有写事务时保持原值。
  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      control_reg       <= 32'b0;
      command_reg       <= 32'b0;
      profile_speed_reg <= 32'b0;
      profile_accel_reg <= 32'b0;
      deadline_reg      <= 64'b0;
      servo_config_reg  <= 32'b0;
      for (write_axis_index = 0; write_axis_index < AXIS_COUNT; write_axis_index = write_axis_index + 1)
        target_reg[write_axis_index] <= 32'b0;
    end else if (axi_need_write_response) begin
      unique case (axi_waddr)
        REG_CONTROL:
          control_reg <= merge_write_bytes(control_reg, axi_wdata_buffer, axi_wstrb_buffer);
        REG_COMMAND:
          command_reg <= merge_write_bytes(command_reg, axi_wdata_buffer, axi_wstrb_buffer);
        REG_PROFILE_SPEED:
          profile_speed_reg <= merge_write_bytes(profile_speed_reg, axi_wdata_buffer, axi_wstrb_buffer);
        REG_PROFILE_ACCEL:
          profile_accel_reg <= merge_write_bytes(profile_accel_reg, axi_wdata_buffer, axi_wstrb_buffer);
        REG_DEADLINE_LO:
          deadline_reg[31:0] <= merge_write_bytes(deadline_reg[31:0], axi_wdata_buffer, axi_wstrb_buffer);
        REG_DEADLINE_HI:
          deadline_reg[63:32] <= merge_write_bytes(deadline_reg[63:32], axi_wdata_buffer, axi_wstrb_buffer);
        REG_SERVO_CONFIG:
          servo_config_reg <= merge_write_bytes(servo_config_reg, axi_wdata_buffer, axi_wstrb_buffer);
        default: begin
          for (write_axis_index = 0; write_axis_index < AXIS_COUNT; write_axis_index = write_axis_index + 1) begin
            if (axi_waddr == (REG_TARGET0 + (write_axis_index * 4)))
              target_reg[write_axis_index] <= merge_write_bytes(
                target_reg[write_axis_index], axi_wdata_buffer, axi_wstrb_buffer
              );
          end
        end
      endcase
    end
  end
endmodule
