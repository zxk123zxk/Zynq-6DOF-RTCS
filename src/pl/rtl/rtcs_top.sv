`timescale 1ns / 1ps
module rtcs_top #(
  parameter int unsigned AXIS_COUNT = 6,
  parameter bit G1_TTL_PORTS = 1'b0,
  parameter int unsigned G2_RESPONSE_TIMEOUT_TICKS = 10_000_000,
  parameter int unsigned G2_FEEDBACK_INTERVAL_TICKS = 5_000_000,
  parameter int unsigned G2_OBSERVE_TIMEOUT_TICKS = 500_000_000,
  // 只有录入并复核安装后的逐轴实测限位，再重新综合，才能开放六轴广播。
  parameter logic [5:0] G2_CALIBRATED_MASK = 6'b0,
  parameter logic [5:0][31:0] G2_SAFE_MIN = '0,
  parameter logic [5:0][31:0] G2_SAFE_MAX = '0,
  parameter logic [5:0][31:0] G2_REFERENCE = '0,
  parameter logic [15:0] G2_SPEED_MAX_RAW = 16'd1500
) (
  input  logic         s_axi_aclk,
  input  logic         s_axi_aresetn,
  input  logic [31:0]  s_axi_awaddr,
  input  logic         s_axi_awvalid,
  output logic         s_axi_awready,
  input  logic [31:0]  s_axi_wdata,
  input  logic [3:0]   s_axi_wstrb,
  input  logic         s_axi_wvalid,
  output logic         s_axi_wready,
  output logic [1:0]   s_axi_bresp,
  output logic         s_axi_bvalid,
  input  logic         s_axi_bready,
  input  logic [31:0]  s_axi_araddr,
  input  logic         s_axi_arvalid,
  output logic         s_axi_arready,
  output logic [31:0]  s_axi_rdata,
  output logic [1:0]   s_axi_rresp,
  output logic         s_axi_rvalid,
  input  logic         s_axi_rready,
  input  logic         servo_rx,
  output logic         servo_tx,
  output logic         servo_tx_en,
  input  logic         estop_n,
  output logic         irq
);
  // 这些内部信号是 AXI 寄存器组与后续运动/总线模块之间的接口。
  import hx30hm_protocol_pkg::*;
  // ABI 12：每个显式提交只发送一帧运动 WRITE；容差与观察期随命令快照。
  localparam logic [63:0] G2_DEADLINE_MAX   = 64'd200_000_000;
  function automatic logic [15:0] abs_diff16(input logic [15:0] a, input logic [15:0] b);
    abs_diff16 = (a >= b) ? (a - b) : (b - a);
  endfunction
  // G1 路径白名单：只读操作与只卸力的 0x28<-0。任何能写位置的帧只能由
  // G2 状态机发起，避免出现绕过物理禁发与反馈验收的第二条运动路径。
  // 白名单和“拒绝”判定共用这一个函数，避免两处条件写歪。
  function automatic logic g1_path_allowed(input logic [7:0] op);
    g1_path_allowed = (op == OP_PING) || (op == OP_READ) ||
                      (op == OP_READ_TORQUE) || (op == OP_TORQUE_OFF);
  endfunction
  logic [63:0] hw_ticks;
  logic [31:0] control, command, status, irq_status, profile_speed, profile_accel, servo_config;
  logic [63:0] deadline;
  logic [31:0] target [0:AXIS_COUNT-1];
  logic [7:0] g1_id, g1_op, g1_servo_error;
  logic g1_start, g1_clear, g1_busy, g1_done, g1_op_blocked;
  logic g1_clear_effective;
  (* mark_debug = "true" *) logic g1_internal_tx, g1_internal_tx_en;
  logic [3:0] g1_fault_code;
  logic [15:0] g1_position;
  logic [31:0] g1_status, g1_result, g1_fault;
  logic [31:0] g2_id, g2_expect, g2_target, g2_speed_time;
  logic [63:0] g2_deadline;
  logic g2_commit, g2_cancel;
  logic [31:0] g2_status, g2_fault, g2_feedback;
  logic [31:0] six_status, six_fault, six_cal_start;
  logic [31:0] six_log_count, six_log_data, six_log_elapsed;
  logic [31:0] six_start, six_result, six_diag;
  logic [5:0][15:0] six_tolerance;
  logic [7:0] six_observe_100ms;
  logic [7:0] six_log_index;
  logic [7:0] limit_id;
  logic [31:0] limit_min, limit_max, limit_home, limit_speed_max;
  logic [31:0] six_feedback [0:5], six_param [0:5];
  logic [63:0] six_deadline;
  logic [1:0] six_command;
  logic six_busy, six_engine_start, six_engine_abort;
  logic [7:0] six_engine_id, six_engine_op;
  logic [15:0] six_engine_position, six_engine_speed, six_engine_time;
  logic [5:0][15:0] sync_position, sync_speed, sync_time;
  logic [5:0][31:0] six_target_packed, six_param_packed;
  typedef enum logic [2:0] {G2_IDLE, G2_READ_START, G2_READ_WAIT,
    G2_WRITE_START, G2_WRITE_WAIT, G2_FEEDBACK_DELAY,
    G2_FEEDBACK_START, G2_FEEDBACK_WAIT} g2_state_t;
  g2_state_t g2_state;
  logic [7:0] g2_id_saved;
  logic [15:0] g2_target_saved, g2_speed_saved, g2_time_saved;
  logic [63:0] g2_deadline_saved;
  logic [63:0] g2_observe_end;
  logic [22:0] feedback_delay;
  logic [1:0] feedback_consecutive;
  logic [7:0] feedback_samples;
  logic g2_done, g2_error, g2_write_sent, g2_late;
  logic [7:0] g2_fault_code;
  logic [15:0] g2_last_position;
  logic [15:0] g2_start_position, g2_tolerance_saved;
  logic [7:0] g2_observe_saved;
  logic g2_start_valid, g2_feedback_valid, g2_position_changed, g2_write_ack;
  logic [7:0] g2_last_servo_error;
  logic engine_start, engine_clear;
  logic [7:0] engine_id, engine_op;
  logic [15:0] engine_position, engine_speed, engine_time;
  (* mark_debug = "true" *) logic [7:0] rx_observed_byte;
  (* mark_debug = "true" *) logic rx_observed_valid;
  (* mark_debug = "true" *) logic rx_protocol_fault;
  (* mark_debug = "true" *) logic tx_direction_disabled;

  // 100 MHz AXI 时钟域的自由运行时间戳，供 PS 设置绝对截止时间。
  always_ff @(posedge s_axi_aclk) begin
    if (!s_axi_aresetn) hw_ticks <= '0;
    else               hw_ticks <= hw_ticks + 64'd1;
  end

  always_comb begin
    limit_min = 0; limit_max = 0; limit_home = 0;
    limit_speed_max = 0;
    if (limit_id >= 8'd1 && limit_id <= 8'd6 &&
        G2_CALIBRATED_MASK[limit_id - 8'd1]) begin
      limit_min = G2_SAFE_MIN[limit_id - 8'd1];
      limit_max = G2_SAFE_MAX[limit_id - 8'd1];
      limit_home = G2_REFERENCE[limit_id - 8'd1];
      limit_speed_max = {16'd0, G2_SPEED_MAX_RAW};
    end
  end

  // ABI 12 使用低 9 位外设内偏移，0x100 以上为结果诊断寄存器。
  axi_lite_regs #(.AXI_ADDR_WIDTH(9), .AXIS_COUNT(AXIS_COUNT)) u_axi_lite_regs (
    .aclk(s_axi_aclk), .aresetn(s_axi_aresetn),
    .saxi_awaddr(s_axi_awaddr[8:0]), .saxi_awvalid(s_axi_awvalid), .saxi_awready(s_axi_awready),
    .saxi_araddr(s_axi_araddr[8:0]), .saxi_arvalid(s_axi_arvalid), .saxi_arready(s_axi_arready),
    .saxi_wready(s_axi_wready), .saxi_wvalid(s_axi_wvalid), .saxi_wdata(s_axi_wdata), .saxi_wstrb(s_axi_wstrb),
    .saxi_rready(s_axi_rready), .saxi_rvalid(s_axi_rvalid), .saxi_rdata(s_axi_rdata), .saxi_rresp(s_axi_rresp),
    .saxi_bready(s_axi_bready), .saxi_bvalid(s_axi_bvalid), .saxi_bresp(s_axi_bresp),
    .hw_ticks(hw_ticks), .status(status), .irq_status(irq_status),
    .g1_status(g1_status), .g1_result(g1_result), .g1_fault(g1_fault),
    .g2_status(g2_status), .g2_fault(g2_fault), .g2_feedback(g2_feedback),
    .g2_start({16'd0, g2_start_position}),
    .g2_six_status(six_status), .g2_six_fault(six_fault),
    .g2_six_cal_start(six_cal_start),
    .g2_six_cal_mask({26'd0, G2_CALIBRATED_MASK}),
    .g2_six_log_count(six_log_count), .g2_six_log_data(six_log_data),
    .g2_six_log_elapsed(six_log_elapsed),
    .g2_six_start(six_start), .g2_six_result(six_result),
    .g2_six_diag(six_diag),
    .g2_limit_min(limit_min), .g2_limit_max(limit_max),
    .g2_limit_home(limit_home), .g2_limit_speed_max(limit_speed_max),
    .g2_six_feedback(six_feedback),
    .control(control), .command(command), .target(target), .profile_speed(profile_speed),
    .profile_accel(profile_accel), .deadline(deadline), .servo_config(servo_config),
    .g1_id(g1_id), .g1_op(g1_op), .g1_start(g1_start), .g1_clear(g1_clear),
    .g2_id(g2_id), .g2_expect(g2_expect), .g2_target(g2_target),
    .g2_speed_time(g2_speed_time), .g2_deadline(g2_deadline),
    .g2_commit(g2_commit), .g2_cancel(g2_cancel),
    .g2_six_param(six_param), .g2_six_deadline(six_deadline),
    .g2_six_command(six_command), .g2_six_log_index(six_log_index),
    .g2_limit_id(limit_id), .g2_six_tolerance(six_tolerance),
    .g2_six_observe_100ms(six_observe_100ms)
  );

  for (genvar axis = 0; axis < 6; axis++) begin : six_descriptor_pack
    assign six_target_packed[axis] = target[axis];
    assign six_param_packed[axis] = six_param[axis];
  end
  g2_six_axis_controller #(
    .CALIBRATED_MASK(G2_CALIBRATED_MASK),
    .SAFE_MIN(G2_SAFE_MIN), .SAFE_MAX(G2_SAFE_MAX),
    .SPEED_MAX_RAW(G2_SPEED_MAX_RAW),
    .FEEDBACK_INTERVAL_TICKS(G2_FEEDBACK_INTERVAL_TICKS),
    .OBSERVE_TIMEOUT_TICKS(G2_OBSERVE_TIMEOUT_TICKS)
  ) u_six (
    .clk(s_axi_aclk), .rst_n(s_axi_aresetn),
    .physical_enabled(G1_TTL_PORTS && estop_n),
    .now_ticks(hw_ticks), .deadline(six_deadline),
    .command(six_command),
    .bus_available(!g1_busy && g2_state == G2_IDLE && !g1_start && !g2_commit),
    .axis_id(g2_id), .delta_raw(g2_expect),
    .target(six_target_packed), .speed_time(six_param_packed),
    .tolerance(six_tolerance), .observe_100ms(six_observe_100ms),
    .result_index(limit_id),
    .engine_done(g1_done), .engine_fault(g1_fault_code),
    .engine_servo_error(g1_servo_error), .engine_position(g1_position),
    .cal_log_index(six_log_index),
    .engine_start(six_engine_start), .engine_abort(six_engine_abort),
    .engine_id(six_engine_id), .engine_op(six_engine_op),
    .engine_write_position(six_engine_position),
    .engine_write_speed(six_engine_speed), .engine_write_time(six_engine_time),
    .sync_position(sync_position), .sync_speed(sync_speed), .sync_time(sync_time),
    .busy(six_busy), .status(six_status), .fault(six_fault),
    .cal_start(six_cal_start), .feedback(six_feedback),
    .cal_log_count(six_log_count), .cal_log_data(six_log_data),
    .cal_log_elapsed(six_log_elapsed),
    .start_position(six_start), .result_flags(six_result), .diag(six_diag)
  );

  hx30hm_g1_engine #(.RESPONSE_TIMEOUT_TICKS(G2_RESPONSE_TIMEOUT_TICKS)) u_g1 (
    .clk(s_axi_aclk), .rst_n(s_axi_aresetn), .clear(engine_clear),
    .start(engine_start),
    .target_id(engine_id), .operation(engine_op),
    .write_position(engine_position), .write_speed(engine_speed),
    .write_time(engine_time),
    .sync_position(sync_position), .sync_speed(sync_speed), .sync_time(sync_time),
    .rx(servo_rx),
    .tx(g1_internal_tx), .tx_enable(g1_internal_tx_en),
    .busy(g1_busy), .done(g1_done), .fault_code(g1_fault_code),
    .servo_error(g1_servo_error), .position_raw(g1_position)
  );

  // Dropping the physical inhibit aborts a packet. Re-arming cannot resume a
  // partially transmitted frame; software must issue a fresh command.
  assign g1_clear_effective = (g1_clear && g2_state == G2_IDLE && !six_busy) ||
                               (G1_TTL_PORTS && !estop_n);
  assign engine_clear = g1_clear_effective || (g2_cancel && g2_state != G2_IDLE) ||
                        six_engine_abort;
  assign engine_start = six_busy ? six_engine_start : (g2_state == G2_IDLE) ?
    (g1_start && G1_TTL_PORTS && estop_n && !g2_commit && six_command == 0 &&
     !g1_busy && g1_path_allowed(g1_op)) :
    ((g2_state == G2_READ_START || g2_state == G2_WRITE_START ||
      g2_state == G2_FEEDBACK_START) && estop_n &&
     (g2_state != G2_WRITE_START || hw_ticks < g2_deadline_saved));
  assign engine_id = six_busy ? six_engine_id : g2_state == G2_IDLE ? g1_id : g2_id_saved;
  assign engine_op = six_busy ? six_engine_op : g2_state == G2_IDLE ? g1_op :
    g2_state == G2_WRITE_START || g2_state == G2_WRITE_WAIT ? OP_TORQUE_MOVE : OP_READ;
  assign engine_position = six_busy ? six_engine_position : g2_target_saved;
  assign engine_speed = six_busy ? six_engine_speed : g2_speed_saved;
  assign engine_time = six_busy ? six_engine_time : g2_time_saved;
  assign g1_status = {28'd0, !(G1_TTL_PORTS && estop_n && s_axi_aresetn),
                      (g1_fault_code != 0) || g1_op_blocked,
                      (g2_state == G2_IDLE) && !six_busy && (g1_done || g1_op_blocked),
                      g1_busy || (g2_state != G2_IDLE) || six_busy};
  assign g1_result = g1_op_blocked ? 32'd0 : {8'd0, g1_servo_error, g1_position};
  assign g1_fault = g1_op_blocked ? 32'd13 : {28'd0, g1_fault_code};
  assign g2_status = {14'd0, g2_position_changed, g2_write_ack,
    feedback_samples, g2_feedback_valid, g2_start_valid,
    g2_late, g2_write_sent,
    !(G1_TTL_PORTS && estop_n && s_axi_aresetn), g2_error, g2_done,
    (g2_state != G2_IDLE)};
  assign g2_fault = {24'd0, g2_fault_code};
  assign g2_feedback = {8'd0, g2_last_servo_error, g2_last_position};

  // One physical bus engine is shared by G1 and G2. A G2 commit snapshots
  // every descriptor field; subsequent MMIO writes cannot change a frame.
  // G2 faults: 1=inhibit, 2=busy, 3=invalid descriptor, 4=deadline,
  // 5=read/protocol, 8=write/servo, 9=observation timeout,
  // 10=cancel. Faults 6/7/11/12 are retired in ABI 08；bit5 仅报告延迟到位。
  // G1 fault 13 = 该操作码不允许经 G1 路径发起（位置类写入只能走 G2 路径）。
  always_ff @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
    if (!s_axi_aresetn) g1_op_blocked <= 1'b0;
    else if (g1_clear) g1_op_blocked <= 1'b0;
    else if (g1_start && g2_state == G2_IDLE && !six_busy && !g1_busy)
      g1_op_blocked <= !g1_path_allowed(g1_op);
  end

  always_ff @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
    if (!s_axi_aresetn) begin
      g2_state <= G2_IDLE;
      g2_id_saved <= 0; g2_target_saved <= 0;
      g2_speed_saved <= 0; g2_time_saved <= 0;
      g2_deadline_saved <= 0; g2_observe_end <= 0;
      feedback_delay <= 0; feedback_consecutive <= 0;
      feedback_samples <= 0; g2_done <= 0; g2_error <= 0;
      g2_write_sent <= 0; g2_late <= 0;
      g2_fault_code <= 0;
      g2_last_position <= 0; g2_last_servo_error <= 0;
      g2_start_position <= 0; g2_tolerance_saved <= 16'd30;
      g2_observe_saved <= 8'd50;
      g2_start_valid <= 0; g2_feedback_valid <= 0;
      g2_position_changed <= 0; g2_write_ack <= 0;
    end else if (!estop_n || g2_cancel) begin
      if (g2_state != G2_IDLE) begin
        g2_done <= 1; g2_error <= 1;
        g2_fault_code <= !estop_n ? 8'd1 : 8'd10;
      end else if (!estop_n && g2_commit) begin
        g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd1;
      end
      g2_state <= G2_IDLE;
    end else begin
      if (g2_commit) begin
        if (g2_state != G2_IDLE) begin
          // In-flight command is immutable; a later explicit commit is needed.
        end else if (g1_busy || g1_start || six_busy || six_command != 0) begin
          if (g2_state == G2_IDLE) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd2;
          end
        end else begin
          g2_done <= 0; g2_error <= 0; g2_fault_code <= 0;
          g2_write_sent <= 0; g2_late <= 0; feedback_samples <= 0;
          feedback_consecutive <= 0; g2_last_position <= 0;
          g2_last_servo_error <= 0;
          g2_start_position <= 0; g2_start_valid <= 0;
          g2_feedback_valid <= 0; g2_position_changed <= 0; g2_write_ack <= 0;
          if (!G1_TTL_PORTS || g2_id < 32'd1 || g2_id > 32'd6 ||
              g2_target[31:16] != 0) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd3;
          end else if (!G2_CALIBRATED_MASK[g2_id[2:0] - 3'd1]) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd11;
          end else if (G2_SAFE_MIN[g2_id[2:0] - 3'd1] >
                       G2_SAFE_MAX[g2_id[2:0] - 3'd1] ||
                       g2_target < G2_SAFE_MIN[g2_id[2:0] - 3'd1] ||
                       g2_target > G2_SAFE_MAX[g2_id[2:0] - 3'd1]) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd12;
          end else if (g2_speed_time[15:0] == 0 ||
                       g2_speed_time[15:0] > G2_SPEED_MAX_RAW) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd15;
          end else if (g2_expect[15:0] == 0 || g2_expect[15:0] > 16'd100 ||
                       g2_expect[31:16] < 16'd10 ||
                       g2_expect[31:16] > 16'd100) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd17;
          end else if (g2_deadline <= hw_ticks ||
                       g2_deadline - hw_ticks > G2_DEADLINE_MAX) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd4;
          end else begin
            g2_id_saved <= g2_id[7:0];
            g2_target_saved <= g2_target[15:0];
            g2_speed_saved <= g2_speed_time[15:0];
            g2_time_saved <= g2_speed_time[31:16];
            g2_tolerance_saved <= g2_expect[15:0];
            g2_observe_saved <= g2_expect[23:16];
            g2_deadline_saved <= g2_deadline;
            g2_state <= G2_READ_START;
          end
        end
      end else case (g2_state)
        G2_IDLE: ;
        G2_READ_START: if (hw_ticks >= g2_deadline_saved) begin
          g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd4;
          g2_state <= G2_IDLE;
        end else g2_state <= G2_READ_WAIT;
        G2_READ_WAIT: if (g1_done) begin
          if (g1_fault_code != 0) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd5;
            g2_state <= G2_IDLE;
          end else begin
            g2_start_position <= g1_position;
            g2_start_valid <= 1;
            g2_state <= G2_WRITE_START;
          end
        end
        G2_WRITE_START: if (hw_ticks >= g2_deadline_saved) begin
          g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd4;
          g2_state <= G2_IDLE;
        end else begin
          g2_write_sent <= 1;
          g2_observe_end <= hw_ticks + 64'(g2_observe_saved) *
                             64'(G2_OBSERVE_TIMEOUT_TICKS / 50);
          g2_state <= G2_WRITE_WAIT;
        end
        G2_WRITE_WAIT: if (g1_done) begin
          if (g1_fault_code != 0) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd8;
            g2_state <= G2_IDLE;
          end else begin
            g2_write_ack <= 1;
            feedback_delay <= 23'(G2_FEEDBACK_INTERVAL_TICKS);
            g2_state <= G2_FEEDBACK_DELAY;
          end
        end
        G2_FEEDBACK_DELAY: if (hw_ticks >= g2_observe_end) begin
          g2_done <= 1; g2_error <= 1;
          g2_fault_code <= g2_feedback_valid && !g2_position_changed &&
            abs_diff16(g2_last_position,g2_target_saved) <= g2_tolerance_saved ?
            8'd16 : 8'd9;
          g2_state <= G2_IDLE;
        end else if (feedback_delay == 0) g2_state <= G2_FEEDBACK_START;
        else feedback_delay <= feedback_delay - 1'b1;
        G2_FEEDBACK_START: g2_state <= G2_FEEDBACK_WAIT;
        G2_FEEDBACK_WAIT: if (hw_ticks >= g2_observe_end) begin
          g2_done <= 1; g2_error <= 1;
          g2_fault_code <= g2_feedback_valid && !g2_position_changed &&
            abs_diff16(g2_last_position,g2_target_saved) <= g2_tolerance_saved ?
            8'd16 : 8'd9;
          g2_state <= G2_IDLE;
        end else if (g1_done) begin
          if (g1_fault_code != 0) begin
            g2_done <= 1; g2_error <= 1; g2_fault_code <= 8'd5;
            g2_state <= G2_IDLE;
          end else begin
            g2_last_position <= g1_position;
            g2_last_servo_error <= g1_servo_error;
            g2_feedback_valid <= 1;
            if (g1_position != g2_start_position) g2_position_changed <= 1;
            feedback_samples <= feedback_samples + 1'b1;
            if (abs_diff16(g1_position, g2_target_saved) <= g2_tolerance_saved &&
                (g2_target_saved == g2_start_position ||
                 g2_position_changed || g1_position != g2_start_position)) begin
              if (feedback_consecutive == 2'd2) begin
                g2_done <= 1;
                if (hw_ticks > g2_deadline_saved) g2_late <= 1;
                g2_state <= G2_IDLE;
              end else begin
                feedback_consecutive <= feedback_consecutive + 1'b1;
                feedback_delay <= 23'(G2_FEEDBACK_INTERVAL_TICKS);
                g2_state <= G2_FEEDBACK_DELAY;
              end
            end else begin
              feedback_consecutive <= 0;
              feedback_delay <= 23'(G2_FEEDBACK_INTERVAL_TICKS);
              g2_state <= G2_FEEDBACK_DELAY;
            end
          end
        end
        default: g2_state <= G2_IDLE;
      endcase
    end
  end

  servo_bus_master u_rx_observer (
    .clk(s_axi_aclk), .rst_n(s_axi_aresetn), .rx(servo_rx),
    .tx(), .tx_enable(tx_direction_disabled), .protocol_fault(rx_protocol_fault),
    .observed_byte(rx_observed_byte), .observed_valid(rx_observed_valid)
  );

  // The safe wrapper remains hard-disabled. Only the TTL wrapper opts in,
  // and a separate pulled-up physical inhibit must be grounded before TX.
  always_comb begin
    servo_tx    = G1_TTL_PORTS ? g1_internal_tx : 1'b1;
    servo_tx_en = G1_TTL_PORTS && s_axi_aresetn && estop_n && g1_internal_tx_en;
    irq         = 1'b0;
    status      = {30'd0, !estop_n, 1'b1}; // bit 0: motion disabled; bit 1: PL TX inhibit
    irq_status  = 32'd0;
  end
endmodule
