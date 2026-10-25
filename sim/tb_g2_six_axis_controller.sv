`timescale 1ns/1ps
module tb_g2_six_axis_controller;
  logic clk=0, rst_n=0, physical_enabled=1, bus_available=1;
  logic [63:0] now_ticks=0, deadline=0;
  logic [1:0] command=0;
  logic [31:0] axis_id=2, delta_raw=50;
  logic [5:0][31:0] target, speed_time;
  logic [5:0][15:0] tolerance={6{16'd15}};
  logic [7:0] observe_100ms=50;
  logic engine_done=0;
  logic [3:0] engine_fault=0;
  logic [7:0] engine_servo_error=0;
  logic [15:0] engine_position=0;
  wire engine_start, engine_abort, busy;
  wire [7:0] engine_id, engine_op;
  wire [15:0] engine_write_position, engine_write_speed, engine_write_time;
  wire [5:0][15:0] sync_position, sync_speed, sync_time;
  wire [31:0] status, fault, cal_start;
  wire [31:0] cal_log_count, cal_log_data, cal_log_elapsed;
  logic [7:0] cal_log_index=0;
  wire [31:0] feedback [0:5];
  wire [31:0] start_position, result_flags, diag;
  logic [5:0][31:0] safe_min, safe_max;
  logic [15:0] live_position [0:5];
  logic force_far=0, fail_id3=0, fail_cal_feedback_id3=0, fail_write=0;
  logic fail_stop_feedback_id3=0, stop_write_seen=0;
  logic fail_status_post_id3=0, fail_status_post_id5=0;
  logic fail_status_post_id6=0, id3_far=0;
  logic [11:0] ignore_mask=0;
  logic fail_status_cal_ack=0;
  integer cal_feedback_shortfall=0;
  integer count_down=0, write_count=0, read_count=0;
  logic [7:0] pending_op, pending_id;
  logic cal_write_seen=0;
  logic [15:0] cal_goal=0;
  logic [1:0] blocked_command=0;
  wire blocked_start;
  wire [31:0] blocked_status, blocked_fault;
  always #5 clk=~clk;
  always @(posedge clk) if (rst_n) now_ticks <= now_ticks+1;
  g2_six_axis_controller #(
    .CALIBRATED_MASK(6'h3f),
    .SAFE_MIN({6{32'd1900}}), .SAFE_MAX({6{32'd2100}}),
    .FEEDBACK_INTERVAL_TICKS(2), .OBSERVE_TIMEOUT_TICKS(400)
  ) dut (
    .clk(clk), .rst_n(rst_n), .physical_enabled(physical_enabled),
    .now_ticks(now_ticks), .deadline(deadline), .command(command),
    .bus_available(bus_available), .axis_id(axis_id), .delta_raw(delta_raw),
    .target(target), .speed_time(speed_time),
    .tolerance(tolerance), .observe_100ms(observe_100ms), .ignore(ignore_mask),
    .result_index(8'd2),
    .engine_done(engine_done), .engine_fault(engine_fault),
    .engine_servo_error(engine_servo_error), .engine_position(engine_position),
    .cal_log_index(cal_log_index),
    .engine_start(engine_start), .engine_abort(engine_abort),
    .engine_id(engine_id), .engine_op(engine_op),
    .engine_write_position(engine_write_position),
    .engine_write_speed(engine_write_speed), .engine_write_time(engine_write_time),
    .sync_position(sync_position), .sync_speed(sync_speed), .sync_time(sync_time),
    .busy(busy), .status(status), .fault(fault), .cal_start(cal_start),
    .cal_log_count(cal_log_count), .cal_log_data(cal_log_data),
    .cal_log_elapsed(cal_log_elapsed),
    .start_position(start_position), .result_flags(result_flags), .diag(diag),
    .feedback(feedback)
  );
  g2_six_axis_controller blocked_by_default (
    .clk(clk), .rst_n(rst_n), .physical_enabled(physical_enabled),
    .now_ticks(now_ticks), .deadline(deadline), .command(blocked_command),
    .bus_available(1'b1), .axis_id(axis_id), .delta_raw(delta_raw),
    .target(target), .speed_time(speed_time),
    .tolerance(tolerance), .observe_100ms(observe_100ms), .ignore(12'd0),
    .result_index(8'd2),
    .engine_done(1'b0), .engine_fault(4'd0), .engine_servo_error(8'd0),
    .engine_position(16'd0), .cal_log_index(8'd0), .engine_start(blocked_start),
    .engine_abort(), .engine_id(), .engine_op(),
    .engine_write_position(), .engine_write_speed(), .engine_write_time(),
    .sync_position(), .sync_speed(), .sync_time(), .busy(),
    .status(blocked_status), .fault(blocked_fault), .cal_start(), .feedback(),
    .cal_log_count(), .cal_log_data(), .cal_log_elapsed(),
    .start_position(), .result_flags(), .diag()
  );
  // 独立假引擎：一次 start 后三拍返回，记录每次 WRITE 和 READ。
  always @(posedge clk) begin
    if (!rst_n) begin
      engine_done <= 0; engine_fault <= 0; engine_servo_error <= 0;
      engine_position <= 0;
      count_down <= 0; write_count <= 0; read_count <= 0;
      pending_op <= 0; pending_id <= 0; cal_write_seen <= 0;
      stop_write_seen <= 0;
      cal_goal <= 0;
    end else if (command == 3) begin
      stop_write_seen <= 0;
    end else if (engine_abort) begin
      engine_done <= 0; count_down <= 0;
    end else if (engine_start) begin
      engine_done <= 0; engine_fault <= 0; engine_servo_error <= 0;
      count_down <= 3;
      pending_op <= engine_op; pending_id <= engine_id;
      if (engine_op == 2) read_count <= read_count+1;
      else begin
        write_count <= write_count+1;
        if (dut.mode == 3) stop_write_seen <= 1;
        if (engine_op == 8) begin
          cal_write_seen <= 1;
          cal_goal <= engine_write_position;
        end
      end
    end else if (count_down != 0) begin
      count_down <= count_down-1;
      if (count_down == 1) begin
        engine_done <= 1;
        if (pending_op == 8 && fail_write) engine_fault <= 3;
        if (pending_op == 8 && fail_status_cal_ack) begin
          engine_fault <= 8; engine_servo_error <= 8'h40;
        end
        if (pending_op == 2) begin
          if (fail_id3 && pending_id == 3) engine_fault <= 3;
          else if (fail_stop_feedback_id3 && pending_id == 3 && stop_write_seen)
            engine_fault <= 3;
          else if (fail_cal_feedback_id3 && pending_id == 3 && cal_write_seen)
            engine_fault <= 3;
          else if (fail_status_post_id3 && pending_id == 3 && write_count != 0) begin
            engine_fault <= 8; engine_servo_error <= 8'h12;
          end else if (fail_status_post_id5 && pending_id == 5 && write_count != 0) begin
            engine_fault <= 8; engine_servo_error <= 8'h24;
          end else if (fail_status_post_id6 && pending_id == 6 && write_count != 0) begin
            engine_fault <= 8; engine_servo_error <= 8'h20;
          end
          else if (force_far) engine_position <= 16'd3000;
          else if (id3_far && pending_id == 3) engine_position <= 16'd2100;
          else if (pending_id == 2 && !cal_write_seen) engine_position <= 16'd2000;
          else if (pending_id == 2 && cal_write_seen)
            engine_position <= 16'(int'(cal_goal)-cal_feedback_shortfall);
          else engine_position <= live_position[pending_id-1];
        end
      end
    end
  end
  task automatic submit(input logic [1:0] op);
    @(negedge clk); deadline=now_ticks+200; command=op;
    @(negedge clk); command=0;
  endtask
  task automatic wait_done;
    int limit=0;
    while (!status[1] && limit<700) begin @(negedge clk); limit++; end
    if (!status[1]) $fatal(1,"controller did not finish");
  endtask
  initial begin
    for (int i=0;i<6;i++) begin
      target[i]=32'(2000+i*10);
      speed_time[i]={16'(10+i),16'(500+i)};
      live_position[i]=16'(2000+i*10);
    end
    target[1]=2000; // fake ID 2 READ starts at 2000 until calibration WRITE.
    repeat (5) @(negedge clk); rst_n=1;
    deadline=now_ticks+200;
    @(negedge clk); blocked_command=1;
    @(negedge clk); blocked_command=0;
    repeat (3) @(negedge clk);
    if (!blocked_status[2] || blocked_fault[7:0]!=11 || blocked_start)
      $fatal(1,"default uncalibrated PL emitted bus command");
    physical_enabled=0;
    submit(1); wait_done();
    if (fault[7:0]!=1 || write_count!=0) $fatal(1,"inhibit emitted WRITE");
    physical_enabled=1;
    target[3]=2200;
    submit(1); wait_done();
    if (fault[7:0]!=12 || fault[15:8]!=4 || write_count!=0)
      $fatal(1,"limit emitted WRITE or lost offending ID");
    target[3]=2030;
    submit(1); wait_done();
    if (status[2] || write_count!=1 || read_count<18 ||
        sync_position[0]!=2000 || sync_position[5]!=2050 ||
        sync_speed[5]!=505 || sync_time[5]!=15)
      $fatal(1,"SYNC motion failed status=%h fault=%h writes=%0d reads=%0d result=%h diag=%h",
             status,fault,write_count,read_count,result_flags,diag);
    // 可以显式重复，不得自动补发。
    submit(1); wait_done();
    if (status[2] || write_count!=2) $fatal(1,"repeat SYNC failed");
    force_far=1;
    submit(1); wait_done();
    if (fault[7:0]!=9 || write_count!=3) $fatal(1,"timeout retried WRITE");
    force_far=0;
    submit(1); wait_done();
    if (status[2] || write_count!=4)
      $fatal(1,"explicit SYNC after feedback timeout did not run");
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    fail_id3=1;
    submit(1); wait_done();
    if (fault[7:0]!=5 || fault[15:8]!=3 || write_count!=1 || diag[15:8]!=3)
      $fatal(1,"absolute WRITE was blocked by READ or lost ID 3 fault=%h writes=%0d diag=%h",
             fault,write_count,diag);
    fail_id3=0;
    submit(1); wait_done();
    if (status[2] || write_count!=2)
      $fatal(1,"explicit SYNC after READ fault did not run");
    // 软件停止 READ 六轴后只发一帧保持广播。
    submit(3); wait_done();
    if (status[2] || write_count!=3 || sync_position[1]!=2000)
      $fatal(1,"software stop did not read then hold");
    tolerance[1]=5;
    submit(2); wait_done();
    if (status[2] || cal_start!=2000 || engine_write_position!=2050 ||
        write_count!=4 || feedback[1][15:0]!=2050)
      $fatal(1,"live 50-count calibration failed");
    submit(2); wait_done();
    if (status[2] || cal_start!=2050 || engine_write_position!=2100 ||
        write_count!=5)
      $fatal(1,"second explicit calibration did not reread live start");
    delta_raw=51;
    submit(2); wait_done();
    if (fault[7:0]!=3 || write_count!=5 || cal_log_count[7:0]!=0 ||
        cal_log_count[16] || cal_log_count[17])
      $fatal(1,"oversized calibration step emitted WRITE or retained stale log");
    // +20 仅走 6 count，虽在旧 ±15 带内，也必须在 5 秒后报 fault 9。
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    axis_id=2; delta_raw=20; cal_feedback_shortfall=14;
    submit(2); wait_done();
    if (fault[7:0]!=9 || !status[4] || status[5] ||
        cal_start!=2000 || cal_log_count[7:0]<3)
      $fatal(1,"partial +6 count calibration incorrectly passed");
    cal_log_index=0; #1;
    if (!cal_log_data[28] || cal_log_data[15:0]!=2006 ||
        cal_log_elapsed==0 || !cal_log_count[17])
      $fatal(1,"calibration feedback log or WRITE ACK missing");
    // 历史故障不阻止下一次显式标定。
    cal_feedback_shortfall=5;
    submit(2); wait_done();
    if (status[2] || status[5] || cal_log_count[7:0]<3 ||
        feedback[1][15:0]!=2030)
      $fatal(1,"manual calibration after fault or +5 boundary failed status=%h fault=%h samples=%d position=%d start=%d goal=%d",
        status,fault,cal_log_count[7:0],feedback[1][15:0],cal_start,cal_goal);
    cal_feedback_shortfall=6;
    submit(2); wait_done();
    if (fault[7:0]!=9) $fatal(1,"+6 target error was accepted");
    submit(1); wait_done();
    if (fault[7:0]==13 || write_count!=4)
      $fatal(1,"historical calibration fault blocked explicit SYNC fault=%h writes=%0d status=%h",
             fault,write_count,status);
    cal_feedback_shortfall=0;
    submit(3); wait_done();
    if (status[2]) $fatal(1,"software stop failed after prior fault");
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    axis_id=3; fail_cal_feedback_id3=1;
    submit(2); wait_done();
    cal_log_index=0; #1;
    if (fault[7:0]!=5 || fault[15:8]!=3 || !cal_log_count[17] ||
        cal_log_count[7:0]!=1 || cal_log_data[28] || cal_log_data[27:24]!=3)
      $fatal(1,"post-WRITE READ fault was not logged with its ID");
    fail_cal_feedback_id3=0;
    fail_write=1;
    submit(2); wait_done();
    if (fault[7:0]!=8 || cal_log_count[17] || cal_log_count[7:0]!=0)
      $fatal(1,"WRITE failure falsely reported ACK or feedback");
    fail_write=0;
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    target[0]=2005; tolerance[0]=30;
    target[1]=2000;
    submit(1); wait_done();
    if (status[2] || write_count!=1 ||
        result_flags[5:0]!=6'h00 || result_flags[13:8]!=6'h3f ||
        result_flags[29:24]!=6'h3f || result_flags[16]==1)
      $fatal(1,"stable absolute feedback was rejected or claimed a start snapshot status=%h fault=%h result=%h writes=%0d",
             status,fault,result_flags,write_count);
    target[0]=2000;
    submit(1); wait_done();
    if (status[2] || write_count!=2)
      $fatal(1,"explicit SYNC after no-change fault was blocked");
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    fail_id3=1;
    submit(3); wait_done();
    if (fault[7:0]!=5 || fault[15:8]!=3 || status[4] ||
        diag[15:8]!=1 || diag[3:0]!=3 || write_count!=0)
      $fatal(1,"stop pre-WRITE READ failure stage/id lost");
    fail_id3=0; fail_stop_feedback_id3=1;
    submit(3); wait_done();
    if (fault[7:0]!=5 || fault[15:8]!=3 || !status[4] ||
        diag[15:8]!=3 || diag[3:0]!=3 || write_count!=1)
      $fatal(1,"stop post-WRITE READ failure stage/id lost");
    fail_stop_feedback_id3=0;
    submit(3); wait_done();
    if (status[2] || write_count!=2)
      $fatal(1,"stop after fault required reset");
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    fail_status_post_id3=1;
    submit(1); wait_done();
    if (fault != 32'h0000_0305 || !status[4] ||
        diag[23:16]!=8'h12 || diag[15:8]!=3 || diag[3:0]!=8 || write_count!=1)
      $fatal(1,"post-WRITE servo ERROR byte/ID lost fault=%h diag=%h",fault,diag);
    fail_status_post_id3=0;
    fail_status_post_id5=1;
    submit(1); wait_done();
    if (fault != 32'h0000_0505 || !status[4] ||
        diag[23:16]!=8'h24 || diag[15:8]!=3 || diag[3:0]!=8 || write_count!=2)
      $fatal(1,"post-WRITE servo ERROR byte/ID lost fault=%h diag=%h",fault,diag);
    fail_status_post_id5=0;
    submit(1); wait_done();
    if (status[2] || diag[23:16]!=0 || diag[3:0]!=0 || write_count!=3)
      $fatal(1,"next explicit command retained prior servo ERROR");
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    axis_id=3; delta_raw=20; fail_status_cal_ack=1;
    submit(2); wait_done();
    if (fault != 32'h0000_0308 || !status[4] || cal_log_count[17] ||
        diag[23:16]!=8'h40 || diag[15:8]!=2 || diag[3:0]!=8 || write_count!=1)
      $fatal(1,"unicast ACK servo ERROR byte/ID lost fault=%h diag=%h",fault,diag);
    fail_status_cal_ack=0;
    // ── 逐轴忽略掩码：错误掩码 bit5=ID6，到位掩码 bit8=ID3 ──
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    fail_status_post_id6=1;
    submit(1); wait_done();
    if (fault[7:0]!=5 || fault[15:8]!=6 || !status[4])
      $fatal(1,"unmasked ID6 servo ERROR was not rejected fault=%h",fault);
    ignore_mask = 12'h020;              // 只屏蔽 ID6 的舵机 ERROR
    submit(1); wait_done();
    if (status[2] || fault[7:0]!=0)
      $fatal(1,"ID6 error mask still failed status=%h fault=%h",status,fault);
    ignore_mask = 0; fail_status_post_id6=0;
    @(negedge clk); rst_n=0;
    repeat (3) @(negedge clk); rst_n=1;
    target[2]=2030; id3_far=1;          // ID3 停在 2100，超 30/15 容差
    submit(1); wait_done();
    if (fault[7:0]!=9)
      $fatal(1,"unmasked ID3 out-of-band was accepted fault=%h",fault);
    ignore_mask = 12'h100;              // 只屏蔽 ID3 的到位判定
    submit(1); wait_done();
    if (status[2] || fault[7:0]!=0)
      $fatal(1,"ID3 arrival mask still failed status=%h fault=%h",status,fault);
    ignore_mask = 0; id3_far=0;
    $display("TB_G2_SIX_AXIS_CONTROLLER_PASS writes=%0d reads=%0d",
      write_count,read_count);
    $finish;
  end
endmodule
