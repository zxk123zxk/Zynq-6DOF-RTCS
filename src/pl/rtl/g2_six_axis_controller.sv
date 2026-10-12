// ABI 14 六轴路径。标定限位是综合时常量；默认掩码为零，广播运动硬拒绝。
// 命令 1=SYNC WRITE，2=现场 READ 后单轴小步，3=READ 六轴后广播保持。
module g2_six_axis_controller #(
  parameter logic [5:0] CALIBRATED_MASK = 6'b0,
  parameter logic [5:0][31:0] SAFE_MIN = '0,
  parameter logic [5:0][31:0] SAFE_MAX = '0,
  parameter logic [15:0] SPEED_MAX_RAW = 16'd1500,
  parameter int unsigned FEEDBACK_INTERVAL_TICKS = 5_000_000,
  parameter int unsigned OBSERVE_TIMEOUT_TICKS = 500_000_000
) (
  input logic clk, rst_n, physical_enabled,
  input logic [63:0] now_ticks, deadline,
  input logic [1:0] command,
  input logic bus_available,
  input logic [31:0] axis_id, delta_raw,
  input logic [5:0][31:0] target,
  input logic [5:0][31:0] speed_time,
  input logic [5:0][15:0] tolerance,
  input logic [7:0] observe_100ms, result_index,
  input logic engine_done,
  input logic [3:0] engine_fault,
  input logic [7:0] engine_servo_error,
  input logic [15:0] engine_position,
  input logic [7:0] cal_log_index,
  output logic engine_start, engine_abort,
  output logic [7:0] engine_id, engine_op,
  output logic [15:0] engine_write_position, engine_write_speed, engine_write_time,
  output logic [5:0][15:0] sync_position, sync_speed, sync_time,
  output logic busy,
  output logic [31:0] status, fault, cal_start,
  output logic [31:0] cal_log_count, cal_log_data, cal_log_elapsed,
  output logic [31:0] start_position, result_flags, diag,
  output logic [31:0] feedback [0:5]
);
  import hx30hm_protocol_pkg::*;
  localparam logic [63:0] MAX_DEADLINE = 64'd200_000_000;
  typedef enum logic [3:0] {
    IDLE, CHECK_GUARD, CAL_READ_START, CAL_READ_WAIT, STOP_CLEAR,
    WRITE_START, WRITE_WAIT, FEEDBACK_DELAY, FEEDBACK_START, FEEDBACK_WAIT
  } state_t;
  state_t state;
  logic [1:0] mode;
  logic [2:0] axis_index;
  logic [1:0] consecutive;
  logic cycle_in_band;
  logic [7:0] samples;
  logic done_flag, error_flag, sent_flag;
  logic [7:0] fault_code, fault_axis;
  logic [63:0] deadline_saved, observe_end;
  logic [63:0] write_tick;
  logic [7:0] log_count;
  logic cal_start_valid, write_ack_reg;
  logic [31:0] log_data_mem [0:127];
  logic [31:0] log_elapsed_mem [0:127];
  logic [15:0] arrival_band;
  logic [22:0] delay_count;
  logic [7:0] cal_id;
  logic signed [15:0] cal_delta;
  logic [15:0] cal_target;
  logic [5:0][31:0] guard_target;
  logic [31:0] guard_speed, guard_accel;
  logic [63:0] guard_deadline;
  logic guard_accepted, guard_rejected;
  logic [2:0] guard_code;
  logic [5:0][15:0] position_saved, speed_saved, time_saved;
  logic [5:0][31:0] candidate_target;
  logic [31:0] feedback_reg [0:5];
  logic [31:0] cal_start_reg;
  logic [31:0] signed_goal;
  logic [2:0] feedback_axis;
  logic [7:0] feedback_id;
  logic [7:0] invalid_speed_axis;
  logic [7:0] invalid_tolerance_axis, observe_saved, phase, engine_fault_saved;
  logic [7:0] servo_error_saved;
  logic [5:0][15:0] tolerance_saved, start_saved;
  logic [5:0] start_valid, feedback_valid, changed_mask, inband_mask;
  logic motion_ok, missing_change, all_last_inband, all_feedback_valid;

  g2_descriptor_guard #(.AXIS_COUNT(6)) u_guard (
    .clk(clk), .rst_n(rst_n), .commit(command == 2'd1 && state == IDLE),
    .target(target), .speed(32'd0), .accel(32'd0),
    .deadline(deadline), .now_ticks(now_ticks),
    .calibrated(CALIBRATED_MASK), .safe_min(SAFE_MIN), .safe_max(SAFE_MAX),
    .inhibit(!physical_enabled),
    .accepted(guard_accepted), .rejected(guard_rejected),
    .reject_code(guard_code), .snapshot_target(guard_target),
    .snapshot_speed(guard_speed), .snapshot_accel(guard_accel),
    .snapshot_deadline(guard_deadline)
  );
  assign busy = state != IDLE;
  assign status = {8'd0, samples, 8'd0, mode,
                   1'b0, sent_flag, !physical_enabled,
                   error_flag, done_flag, busy};
  assign fault = {16'd0, fault_axis, fault_code};
  assign cal_start = cal_start_reg;
  assign cal_log_count = {14'd0, write_ack_reg, cal_start_valid, 8'd0, log_count};
  assign cal_log_data = cal_log_index < log_count ? log_data_mem[cal_log_index[6:0]] : 32'd0;
  assign cal_log_elapsed = cal_log_index < log_count ?
    log_elapsed_mem[cal_log_index[6:0]] : 32'd0;
  assign start_position = result_index >= 1 && result_index <= 6 ?
    {16'd0, start_saved[result_index-8'd1]} : 32'd0;
  assign result_flags = {2'd0, inband_mask, 2'd0, changed_mask,
                         2'd0, feedback_valid, 2'd0, start_valid};
  assign diag = {8'd0, servo_error_saved, phase, 4'd0, engine_fault_saved[3:0]};
  assign arrival_band = tolerance_saved[feedback_axis];
  for (genvar axis = 0; axis < 6; axis++) begin : feedback_assign
    assign feedback[axis] = feedback_reg[axis];
  end
  assign engine_abort = (command == 2'd3 && state != IDLE);
  assign engine_start = (state == CAL_READ_START || state == FEEDBACK_START ||
                         state == WRITE_START) && physical_enabled &&
                         (state != WRITE_START || now_ticks < deadline_saved);
  assign engine_id = (state == CAL_READ_START || state == WRITE_START && mode == 2'd2 ||
                      state == FEEDBACK_START && mode == 2'd2) ? cal_id :
                     (state == WRITE_START ? BROADCAST_ID : feedback_id);
  assign engine_op = state == WRITE_START ?
    (mode == 2'd2 ? OP_TORQUE_MOVE : OP_SYNC_TORQUE_MOVE) : OP_READ;
  assign engine_write_position = cal_target;
  assign engine_write_speed = 16'd500;
  assign engine_write_time = 16'd10;
  assign sync_position = position_saved;
  assign sync_speed = speed_saved;
  assign sync_time = time_saved;
  assign feedback_axis = mode == 2'd2 ? (cal_id[2:0] - 3'd1) : axis_index;
  assign feedback_id = mode == 2'd2 ? cal_id : ({5'd0, axis_index} + 8'd1);

  always_comb begin
    signed_goal = {16'd0, engine_position} + {{16{cal_delta[15]}}, cal_delta};
  end
  always_comb begin
    invalid_speed_axis = 0;
    for (int axis = 5; axis >= 0; axis--)
      if (speed_time[axis][15:0] == 0 ||
          speed_time[axis][15:0] > SPEED_MAX_RAW)
        invalid_speed_axis = 8'(axis + 1);
  end
  always_comb begin
    invalid_tolerance_axis = 0;
    for (int axis = 5; axis >= 0; axis--)
      if (tolerance[axis] == 0 || tolerance[axis] > 16'd100)
        invalid_tolerance_axis = 8'(axis + 1);
    motion_ok = 1;
    missing_change = 0;
    all_last_inband = 1;
    all_feedback_valid = 1;
    for (int axis = 0; axis < 6; axis++) begin
      if (start_valid[axis] && position_saved[axis] != start_saved[axis] &&
          !changed_mask[axis]) begin
        missing_change = 1;
        if (!(engine_done && engine_fault == 0 &&
              feedback_axis == 3'(axis) && engine_position != start_saved[axis]))
          motion_ok = 0;
      end
      if (start_valid[axis] && !inband_mask[axis]) all_last_inband = 0;
      if (start_valid[axis] && !feedback_valid[axis]) all_feedback_valid = 0;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      mode <= 0; axis_index <= 0; consecutive <= 0; cycle_in_band <= 1;
      samples <= 0; done_flag <= 0; error_flag <= 0; sent_flag <= 0;
      fault_code <= 0; fault_axis <= 0;
      deadline_saved <= 0; observe_end <= 0; write_tick <= 0; delay_count <= 0;
      log_count <= 0; cal_start_valid <= 0; write_ack_reg <= 0;
      cal_id <= 0; cal_delta <= 0; cal_target <= 0; cal_start_reg <= 0;
      position_saved <= '0; speed_saved <= '0; time_saved <= '0;
      tolerance_saved <= {6{16'd30}}; observe_saved <= 8'd50;
      start_saved <= '0; start_valid <= 0; feedback_valid <= 0;
      changed_mask <= 0; inband_mask <= 0; phase <= 0; engine_fault_saved <= 0;
      servo_error_saved <= 0;
      candidate_target <= '0;
      for (int i = 0; i < 6; i++) feedback_reg[i] <= 0;
    end else if (!physical_enabled && state != IDLE) begin
      state <= IDLE; done_flag <= 1; error_flag <= 1; fault_code <= 8'd1;
      fault_axis <= feedback_id;
    end else if (command == 2'd3 && state != IDLE) begin
      // 软件 stop 抢占正在观测的命令；串口引擎同步清空，不续发残帧。
      state <= STOP_CLEAR; mode <= 2'd3; done_flag <= 0; error_flag <= 0;
      sent_flag <= 0; samples <= 0; consecutive <= 0; axis_index <= 0;
      cycle_in_band <= 1; deadline_saved <= deadline;
      start_saved <= '0; start_valid <= 0; feedback_valid <= 0;
      changed_mask <= 0; inband_mask <= 0;
      phase <= 8'd1; engine_fault_saved <= 0; servo_error_saved <= 0;
      fault_code <= 0; fault_axis <= 0;
    end else if (command != 0 && state == IDLE) begin
      done_flag <= 0; error_flag <= 0; sent_flag <= 0;
      fault_code <= 0; fault_axis <= 0; samples <= 0;
      phase <= 0; engine_fault_saved <= 0; servo_error_saved <= 0;
      start_saved <= '0; start_valid <= 0; feedback_valid <= 0;
      changed_mask <= 0; inband_mask <= 0;
      consecutive <= 0; cycle_in_band <= 1; axis_index <= 0;
      deadline_saved <= deadline; mode <= command;
      tolerance_saved <= tolerance;
      observe_saved <= command == 2'd3 ? 8'd50 : observe_100ms;
      if (command == 2'd2) begin
        log_count <= 0; cal_start_reg <= 0;
        cal_start_valid <= 0; write_ack_reg <= 0;
      end
      if (!bus_available) begin
        done_flag <= 1; error_flag <= 1; fault_code <= 8'd2;
      end else if (!physical_enabled) begin
        done_flag <= 1; error_flag <= 1; fault_code <= 8'd1;
      end else if (deadline <= now_ticks || deadline - now_ticks > MAX_DEADLINE) begin
        done_flag <= 1; error_flag <= 1; fault_code <= 8'd4;
      end else if (command == 2'd1) begin
        if (invalid_speed_axis != 0) begin
          done_flag <= 1; error_flag <= 1;
          fault_code <= 8'd15; fault_axis <= invalid_speed_axis;
        end else if (invalid_tolerance_axis != 0) begin
          done_flag <= 1; error_flag <= 1;
          fault_code <= 8'd17; fault_axis <= invalid_tolerance_axis;
        end else if (observe_100ms < 8'd10 || observe_100ms > 8'd100) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd18;
        end else begin
          candidate_target <= target;
          for (int i = 0; i < 6; i++) begin
            speed_saved[i] <= speed_time[i][15:0];
            time_saved[i] <= speed_time[i][31:16];
          end
          state <= CHECK_GUARD;
        end
      end else if (command == 2'd2) begin
        if (axis_id < 2 || axis_id > 6 ||
            delta_raw[31:16] != {16{delta_raw[15]}} ||
            $signed(delta_raw) == 0 ||
            $signed(delta_raw) < -32'sd50 || $signed(delta_raw) > 32'sd50) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd3;
        end else if (tolerance[axis_id[2:0]-3'd1] == 0 ||
                     tolerance[axis_id[2:0]-3'd1] > 16'd100) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd17;
          fault_axis <= axis_id[7:0];
        end else if (observe_100ms < 8'd10 || observe_100ms > 8'd100) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd18;
        end else begin
          cal_id <= axis_id[7:0]; cal_delta <= delta_raw[15:0];
          phase <= 8'd1; state <= CAL_READ_START;
        end
      end else begin
        phase <= 8'd1; state <= STOP_CLEAR;
      end
    end else case (state)
      IDLE: ;
      CHECK_GUARD: begin
        if (guard_rejected) begin
          done_flag <= 1; error_flag <= 1;
          if (guard_code == 3'd4) begin
            for (int i = 0; i < 6; i++) begin
              if (SAFE_MIN[i] > SAFE_MAX[i] || SAFE_MAX[i] > 32'd65535 ||
                  candidate_target[i][31:16] != 0 ||
                  candidate_target[i] < SAFE_MIN[i] ||
                  candidate_target[i] > SAFE_MAX[i]) fault_axis <= 8'(i + 1);
            end
          end
          case (guard_code)
            3'd1: fault_code <= 8'd11;
            3'd2: fault_code <= 8'd1;
            3'd3: fault_code <= 8'd4;
            3'd4: fault_code <= 8'd12;
            default: fault_code <= 8'd3;
          endcase
          state <= IDLE;
        end else if (guard_accepted) begin
          for (int i = 0; i < 6; i++) position_saved[i] <= guard_target[i][15:0];
          // Absolute targets need no start-position READ. Only relative
          // calibration and stop retain their functional pre-WRITE READ.
          phase <= 8'd2; state <= WRITE_START;
        end
      end
      STOP_CLEAR: begin
        if (now_ticks >= deadline_saved) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd4; state <= IDLE;
        end else state <= FEEDBACK_START;
      end
      CAL_READ_START: begin
        if (now_ticks >= deadline_saved) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd4; state <= IDLE;
        end else state <= CAL_READ_WAIT;
      end
      CAL_READ_WAIT: if (engine_done) begin
        if (engine_fault != 0) begin
          engine_fault_saved <= {4'd0, engine_fault};
          servo_error_saved <= engine_servo_error;
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd5;
          fault_axis <= cal_id; state <= IDLE;
        end else if (signed_goal[31:16] != 0) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd3; state <= IDLE;
        end else if (!CALIBRATED_MASK[cal_id[2:0] - 3'd1]) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd11;
          fault_axis <= cal_id; state <= IDLE;
        end else if (SAFE_MIN[cal_id[2:0] - 3'd1] > SAFE_MAX[cal_id[2:0] - 3'd1] ||
                     signed_goal < $signed(SAFE_MIN[cal_id[2:0] - 3'd1]) ||
                     signed_goal > $signed(SAFE_MAX[cal_id[2:0] - 3'd1])) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd12;
          fault_axis <= cal_id; state <= IDLE;
        end else begin
          cal_start_reg <= {16'd0, engine_position};
          cal_start_valid <= 1;
          start_saved[cal_id - 1] <= engine_position;
          start_valid[cal_id - 1] <= 1;
          cal_target <= signed_goal[15:0];
          position_saved[cal_id - 1] <= signed_goal[15:0];
          feedback_reg[cal_id - 1] <= {8'd0, engine_servo_error, engine_position};
          phase <= 8'd2; state <= WRITE_START;
        end
      end
      WRITE_START: if (now_ticks >= deadline_saved) begin
        done_flag <= 1; error_flag <= 1; fault_code <= 8'd4; state <= IDLE;
      end else begin
        sent_flag <= 1;
        phase <= 8'd2;
        write_tick <= now_ticks;
        observe_end <= now_ticks + 64'(observe_saved) *
                       64'(OBSERVE_TIMEOUT_TICKS / 50);
        state <= WRITE_WAIT;
      end
      WRITE_WAIT: if (engine_done) begin
        if (engine_fault != 0) begin
          engine_fault_saved <= {4'd0, engine_fault};
          servo_error_saved <= engine_servo_error;
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd8;
          fault_axis <= mode == 2'd2 ? cal_id : 8'd0;
          state <= IDLE;
        end else begin
          if (mode == 2'd2) write_ack_reg <= 1;
          phase <= 8'd3;
          delay_count <= 23'(FEEDBACK_INTERVAL_TICKS);
          axis_index <= 0; cycle_in_band <= 1; state <= FEEDBACK_DELAY;
        end
      end
      FEEDBACK_DELAY: if (now_ticks >= observe_end) begin
        done_flag <= 1; error_flag <= 1;
        fault_code <= all_last_inband && all_feedback_valid && missing_change ?
                      8'd16 : 8'd9;
        if (mode == 2'd2) fault_axis <= cal_id;
        state <= IDLE;
      end else if (delay_count == 0) state <= FEEDBACK_START;
      else delay_count <= delay_count - 1'b1;
      FEEDBACK_START: if (mode == 2'd3 && !sent_flag && now_ticks >= deadline_saved) begin
        done_flag <= 1; error_flag <= 1; fault_code <= 8'd4; state <= IDLE;
      end else state <= FEEDBACK_WAIT;
      FEEDBACK_WAIT: begin
        // Arm the next observation delay on READ completion. Its enable must
        // not depend on the current position comparison or stability result.
        if (engine_done) delay_count <= 23'(FEEDBACK_INTERVAL_TICKS);
        if (now_ticks >= observe_end && sent_flag) begin
        done_flag <= 1; error_flag <= 1;
        fault_code <= all_last_inband && all_feedback_valid && missing_change ?
                      8'd16 : 8'd9;
        fault_axis <= feedback_id;
        state <= IDLE;
      end else if (engine_done) begin
        if (mode == 2'd2 && sent_flag && log_count >= 8'd128) begin
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd14;
          fault_axis <= cal_id; state <= IDLE;
        end else if (engine_fault != 0) begin
          engine_fault_saved <= {4'd0, engine_fault};
          servo_error_saved <= engine_servo_error;
          if (mode == 2'd2 && sent_flag) begin
            log_data_mem[log_count[6:0]] <= {3'd0, 1'b0, engine_fault,
                                            engine_servo_error, 16'd0};
            log_elapsed_mem[log_count[6:0]] <= 32'(now_ticks - write_tick);
            log_count <= log_count + 1'b1;
          end
          done_flag <= 1; error_flag <= 1; fault_code <= 8'd5;
          fault_axis <= feedback_id;
          state <= IDLE;
        end else begin
          if (mode == 2'd2 && sent_flag) begin
            log_data_mem[log_count[6:0]] <= {3'd0, 1'b1, 4'd0,
                                            engine_servo_error, engine_position};
            log_elapsed_mem[log_count[6:0]] <= 32'(now_ticks - write_tick);
            log_count <= log_count + 1'b1;
          end
          feedback_reg[feedback_axis] <=
            {8'd0, engine_servo_error, engine_position};
          if (mode == 2'd3 && !sent_flag) begin
            start_saved[axis_index] <= engine_position;
            start_valid[axis_index] <= 1;
            if (mode == 2'd3) begin
              position_saved[axis_index] <= engine_position;
              speed_saved[axis_index] <= 16'd1500;
              time_saved[axis_index] <= 16'd10;
            end
          end else begin
            samples <= samples + 1'b1;
            feedback_valid[feedback_axis] <= 1;
            if (start_valid[feedback_axis] &&
                engine_position != start_saved[feedback_axis])
              changed_mask[feedback_axis] <= 1;
            inband_mask[feedback_axis] <=
              (engine_position > position_saved[feedback_axis] ?
               engine_position-position_saved[feedback_axis] :
               position_saved[feedback_axis]-engine_position) <= arrival_band;
            if ((engine_position > position_saved[feedback_axis] ?
              engine_position - position_saved[feedback_axis] :
              position_saved[feedback_axis] - engine_position) > arrival_band) begin
              cycle_in_band <= 0;
              fault_axis <= feedback_id;
            end
          end
          if (mode != 2'd2 && axis_index != 3'd5) begin
            axis_index <= axis_index + 1'b1;
            state <= FEEDBACK_START;
          end else if (mode == 2'd3 && !sent_flag) begin
            axis_index <= 0;
            phase <= 8'd2; state <= WRITE_START;
          end else if (cycle_in_band && motion_ok &&
            (engine_position > position_saved[feedback_axis] ?
              engine_position - position_saved[feedback_axis] :
              position_saved[feedback_axis] - engine_position) <= arrival_band) begin
            if (consecutive == 2'd2) begin
              done_flag <= 1; state <= IDLE;
            end else begin
              consecutive <= consecutive + 1'b1;
              cycle_in_band <= 1; axis_index <= 0;
              state <= FEEDBACK_DELAY;
            end
          end else begin
            consecutive <= 0; cycle_in_band <= 1; axis_index <= 0;
            state <= FEEDBACK_DELAY;
          end
        end
      end
      end
      default: state <= IDLE;
    endcase
  end
endmodule
