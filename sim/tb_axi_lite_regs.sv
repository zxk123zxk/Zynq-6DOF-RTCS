`timescale 1ns / 1ps

// AXI4-Lite register-bank regression.  This testbench intentionally targets
// axi_lite_regs directly: it verifies the PS-visible register contract without
// involving board pins, servo logic, or the RTCS top-level safety gate.
module tb_axi_lite_regs;
  import rtcs_pkg::*;

  localparam int unsigned AXIS_COUNT = 6;

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic [31:0] s_axi_awaddr;
  logic s_axi_awvalid;
  logic s_axi_awready;
  logic [31:0] s_axi_wdata;
  logic [3:0] s_axi_wstrb;
  logic s_axi_wvalid;
  logic s_axi_wready;
  logic [1:0] s_axi_bresp;
  logic s_axi_bvalid;
  logic s_axi_bready;
  logic [31:0] s_axi_araddr;
  logic s_axi_arvalid;
  logic s_axi_arready;
  logic [31:0] s_axi_rdata;
  logic [1:0] s_axi_rresp;
  logic s_axi_rvalid;
  logic s_axi_rready;
  logic [63:0] hw_ticks;
  logic [31:0] control;
  logic [31:0] command;
  logic [31:0] status;
  logic [31:0] irq_status;
  logic [31:0] target [0:AXIS_COUNT-1];
  logic [31:0] profile_speed;
  logic [31:0] profile_accel;
  logic [63:0] deadline;
  logic [31:0] servo_config;
  logic [31:0] g1_status = 32'h0000_0008;
  logic [31:0] g1_result = 32'h0000_0518;
  logic [31:0] g1_fault = 32'h0000_0003;
  logic [7:0] g1_id, g1_op;
  logic g1_start, g1_clear;
  integer start_count = 0, clear_count = 0;
  always @(posedge clk) if (rst_n) begin
    if (g1_start) start_count = start_count + 1;
    if (g1_clear) clear_count = clear_count + 1;
  end

  axi_lite_regs #(.AXI_ADDR_WIDTH(8), .AXIS_COUNT(AXIS_COUNT)) dut (
    .aclk(clk), .aresetn(rst_n),
    .saxi_awaddr(s_axi_awaddr[7:0]), .saxi_awvalid(s_axi_awvalid), .saxi_awready(s_axi_awready),
    .saxi_araddr(s_axi_araddr[7:0]), .saxi_arvalid(s_axi_arvalid), .saxi_arready(s_axi_arready),
    .saxi_wready(s_axi_wready), .saxi_wvalid(s_axi_wvalid), .saxi_wdata(s_axi_wdata), .saxi_wstrb(s_axi_wstrb),
    .saxi_rready(s_axi_rready), .saxi_rvalid(s_axi_rvalid), .saxi_rdata(s_axi_rdata), .saxi_rresp(s_axi_rresp),
    .saxi_bready(s_axi_bready), .saxi_bvalid(s_axi_bvalid), .saxi_bresp(s_axi_bresp),
    .hw_ticks(hw_ticks), .status(status), .irq_status(irq_status),
    .g1_status(g1_status), .g1_result(g1_result), .g1_fault(g1_fault),
    .control(control), .command(command), .target(target), .profile_speed(profile_speed),
    .profile_accel(profile_accel), .deadline(deadline), .servo_config(servo_config),
    .g1_id(g1_id), .g1_op(g1_op), .g1_start(g1_start), .g1_clear(g1_clear)
  );

  always #5 clk = ~clk;

  task automatic require(input logic condition, input string message);
    if (!condition) $fatal(1, "ASSERTION FAILED: %s", message);
  endtask

  task automatic finish_write_response;
    integer wait_cycle;
    logic response_seen;
    begin
      response_seen = 1'b0;
      for (wait_cycle = 0; wait_cycle < 20; wait_cycle = wait_cycle + 1) begin
        @(posedge clk);
        if (s_axi_bvalid) response_seen = 1'b1;
      end
      require(response_seen && s_axi_bvalid, "write response timed out");
      require(s_axi_bresp == 2'b00, "write response must be OKAY");
      repeat (2) begin
        @(posedge clk);
        require(s_axi_bvalid, "BVALID must remain asserted until BREADY");
      end
      @(negedge clk) s_axi_bready = 1'b1;
      @(posedge clk);
      #1 require(!s_axi_bvalid, "BVALID must clear after BREADY handshake");
      @(negedge clk) s_axi_bready = 1'b0;
    end
  endtask

  task automatic write_addr_first(
    input logic [31:0] address, input logic [31:0] data, input logic [3:0] strobe
  );
    begin
      @(negedge clk);
      s_axi_awaddr = address;
      s_axi_awvalid = 1'b1;
      @(posedge clk);
      require(s_axi_awready, "AW channel did not accept address");
      @(negedge clk) s_axi_awvalid = 1'b0;
      @(negedge clk);
      s_axi_wdata = data;
      s_axi_wstrb = strobe;
      s_axi_wvalid = 1'b1;
      @(posedge clk);
      require(s_axi_wready, "W channel did not accept data");
      @(negedge clk) s_axi_wvalid = 1'b0;
      finish_write_response();
    end
  endtask

  task automatic write_data_first(
    input logic [31:0] address, input logic [31:0] data, input logic [3:0] strobe
  );
    begin
      @(negedge clk);
      s_axi_wdata = data;
      s_axi_wstrb = strobe;
      s_axi_wvalid = 1'b1;
      @(posedge clk);
      require(s_axi_wready, "W-first transaction did not accept data");
      @(negedge clk) s_axi_wvalid = 1'b0;
      @(negedge clk);
      s_axi_awaddr = address;
      s_axi_awvalid = 1'b1;
      @(posedge clk);
      require(s_axi_awready, "W-first transaction did not accept address");
      @(negedge clk) s_axi_awvalid = 1'b0;
      finish_write_response();
    end
  endtask

  task automatic write_same_cycle(
    input logic [31:0] address, input logic [31:0] data, input logic [3:0] strobe
  );
    begin
      @(negedge clk);
      s_axi_awaddr = address;
      s_axi_awvalid = 1'b1;
      s_axi_wdata = data;
      s_axi_wstrb = strobe;
      s_axi_wvalid = 1'b1;
      @(posedge clk);
      require(s_axi_awready && s_axi_wready, "same-cycle AW/W handshake failed");
      @(negedge clk);
      s_axi_awvalid = 1'b0;
      s_axi_wvalid = 1'b0;
      finish_write_response();
    end
  endtask

  task automatic read_register(input logic [31:0] address, output logic [31:0] value);
    logic [31:0] held_value;
    integer wait_cycle;
    logic response_seen;
    begin
      @(negedge clk);
      s_axi_araddr = address;
      s_axi_arvalid = 1'b1;
      @(posedge clk);
      require(s_axi_arready, "AR channel did not accept address");
      @(negedge clk) s_axi_arvalid = 1'b0;
      response_seen = 1'b0;
      for (wait_cycle = 0; wait_cycle < 20; wait_cycle = wait_cycle + 1) begin
        @(posedge clk);
        if (s_axi_rvalid) response_seen = 1'b1;
      end
      require(response_seen && s_axi_rvalid, "read response timed out");
      require(s_axi_rresp == 2'b00, "read response must be OKAY");
      held_value = s_axi_rdata;
      repeat (2) begin
        @(posedge clk);
        require(s_axi_rvalid, "RVALID must remain asserted until RREADY");
        require(s_axi_rdata == held_value, "RDATA must remain stable before RREADY");
      end
      value = held_value;
      @(negedge clk) s_axi_rready = 1'b1;
      @(posedge clk);
      #1 require(!s_axi_rvalid, "RVALID must clear after RREADY handshake");
      @(negedge clk) s_axi_rready = 1'b0;
    end
  endtask

  logic [31:0] readback;
  integer axis;

  initial begin
    s_axi_awaddr = '0;
    s_axi_awvalid = 1'b0;
    s_axi_wdata = '0;
    s_axi_wstrb = '0;
    s_axi_wvalid = 1'b0;
    s_axi_bready = 1'b0;
    s_axi_araddr = '0;
    s_axi_arvalid = 1'b0;
    s_axi_rready = 1'b0;
    hw_ticks = 64'h0123_4567_89ab_cdef;
    status = 32'h0bad_f00d;
    irq_status = 32'h00c0_ffee;

    repeat (2) @(posedge clk);
    #1;
    require(!s_axi_awready && !s_axi_wready && !s_axi_arready,
            "ready signals must be low while reset is asserted");
    require(!s_axi_bvalid && !s_axi_rvalid, "response valids must reset low");
    require(control == '0 && command == '0 && profile_speed == '0 &&
            profile_accel == '0 && deadline == '0 && servo_config == '0 &&
            g1_id == 0 && g1_op == 0 && !g1_start && !g1_clear,
            "all writable scalar registers must reset to zero");
    for (axis = 0; axis < AXIS_COUNT; axis = axis + 1)
      require(target[axis] == '0, "all six target registers must reset to zero");

    @(negedge clk) rst_n = 1'b1;
    @(posedge clk);
    #1 require(s_axi_awready && s_axi_wready && s_axi_arready,
               "ready signals must assert after reset release");

    read_register(REG_ID_VERSION, readback);
    require(readback == ID_VERSION, "ID_VERSION readback mismatch");
    read_register(REG_STATUS, readback);
    require(readback == status, "STATUS readback mismatch");
    read_register(REG_IRQ_STATUS, readback);
    require(readback == irq_status, "IRQ_STATUS readback mismatch");
    read_register(REG_TICKS_LO, readback);
    require(readback == hw_ticks[31:0], "HW_TICKS_LO readback mismatch");
    read_register(REG_TICKS_HI, readback);
    require(readback == hw_ticks[63:32], "HW_TICKS_HI readback mismatch");

    write_addr_first(REG_CONTROL, 32'ha1b2_c3d4, 4'b1111);
    read_register(REG_CONTROL, readback);
    require(readback == 32'ha1b2_c3d4, "full CONTROL write mismatch");
    write_data_first(REG_CONTROL, 32'h00ee_00ff, 4'b0101);
    read_register(REG_CONTROL, readback);
    require(readback == 32'ha1ee_c3ff, "partial CONTROL byte merge mismatch");

    write_same_cycle(REG_COMMAND, 32'h0001_00a5, 4'b1111);
    read_register(REG_COMMAND, readback);
    require(readback == 32'h0001_00a5, "same-cycle COMMAND write mismatch");
    write_same_cycle(REG_PROFILE_SPEED, 32'h1122_3344, 4'b1111);
    write_data_first(REG_DEADLINE_LO, 32'h5566_7788, 4'b1111);
    write_addr_first(REG_DEADLINE_HI, 32'h99aa_bbcc, 4'b1111);
    read_register(REG_PROFILE_SPEED, readback);
    require(readback == 32'h1122_3344, "PROFILE_SPEED readback mismatch");
    read_register(REG_DEADLINE_LO, readback);
    require(readback == 32'h5566_7788, "DEADLINE_LO readback mismatch");
    read_register(REG_DEADLINE_HI, readback);
    require(readback == 32'h99aa_bbcc, "DEADLINE_HI readback mismatch");

    for (axis = 0; axis < AXIS_COUNT; axis = axis + 1) begin
      if (axis % 3 == 0)
        write_addr_first(REG_TARGET0 + (axis * 4), 32'h6100_0000 + axis, 4'b1111);
      else if (axis % 3 == 1)
        write_data_first(REG_TARGET0 + (axis * 4), 32'h6100_0000 + axis, 4'b1111);
      else
        write_same_cycle(REG_TARGET0 + (axis * 4), 32'h6100_0000 + axis, 4'b1111);
    end
    for (axis = 0; axis < AXIS_COUNT; axis = axis + 1) begin
      read_register(REG_TARGET0 + (axis * 4), readback);
      require(readback == (32'h6100_0000 + axis), "target register readback mismatch");
      require(target[axis] == (32'h6100_0000 + axis), "target register output mismatch");
    end

    write_same_cycle(REG_G1_ID, 32'h0000_0006, 4'hf);
    write_same_cycle(REG_G1_OP, 32'h0000_0002, 4'hf);
    read_register(REG_G1_ID, readback);
    require(readback == 6 && g1_id == 6, "G1 ID mismatch");
    read_register(REG_G1_OP, readback);
    require(readback == 2 && g1_op == 2, "G1 opcode mismatch");
    read_register(REG_G1_STATUS, readback);
    require(readback == g1_status, "G1 status mismatch");
    read_register(REG_G1_RESULT, readback);
    require(readback == g1_result, "G1 result mismatch");
    read_register(REG_G1_FAULT, readback);
    require(readback == g1_fault, "G1 fault mismatch");
    write_same_cycle(REG_G1_ID, 32'h0000_00ff, 4'b0010);
    require(g1_id == 6, "G1 ID must honor WSTRB");
    write_same_cycle(REG_G1_CMD, 32'd1, 4'b0001);
    require(!g1_start, "partial command must not start");
    require(start_count == 0, "partial command pulse occurred");
    write_same_cycle(REG_G1_CMD, 32'd1, 4'hf);
    require(start_count == 1, "full command must pulse exactly once");
    write_same_cycle(REG_G1_CMD, 32'd2, 4'hf);
    require(clear_count == 1, "clear command must pulse exactly once");

    $display("TB_AXI_LITE_REGS_PASS");
    $finish;
  end
endmodule
