`timescale 1ns/1ps
module tb_g2_board_limits;
  import g2_board_limits_pkg::*;
  logic clk=0, rst_n=0, physical_enabled=1;
  logic [63:0] now_ticks=0, deadline=0;
  logic [1:0] command=0;
  logic [5:0][31:0] target='0, speed_time='0;
  logic [31:0] axis_id=2, delta_raw=1;
  logic engine_done=0;
  logic [15:0] engine_position=0;
  wire engine_start;
  wire [7:0] engine_op,engine_id;
  wire [5:0][15:0] sync_position, sync_speed, sync_time;
  wire [31:0] status, fault;
  always #5 clk=~clk;
  always @(posedge clk) if (rst_n) now_ticks<=now_ticks+1;
  g2_six_axis_controller #(
    .CALIBRATED_MASK(CALIBRATED_MASK), .SAFE_MIN(SAFE_MIN),
    .SAFE_MAX(SAFE_MAX), .SPEED_MAX_RAW(SPEED_MAX_RAW),
    .FEEDBACK_INTERVAL_TICKS(2), .OBSERVE_TIMEOUT_TICKS(200)
  ) dut (
    .clk(clk),.rst_n(rst_n),.physical_enabled(physical_enabled),
    .now_ticks(now_ticks),.deadline(deadline),.command(command),
    .bus_available(1'b1),.axis_id(axis_id),.delta_raw(delta_raw),
    .target(target),.speed_time(speed_time),
    .tolerance({6{16'd30}}),.observe_100ms(8'd50),.result_index(8'd1),
    .engine_done(engine_done),
    .engine_fault(4'd0),.engine_servo_error(8'd0),
    .engine_position(engine_position),.cal_log_index(8'd0),
    .engine_start(engine_start),.engine_abort(),.engine_id(engine_id),
    .engine_op(engine_op),.engine_write_position(),
    .engine_write_speed(),.engine_write_time(),
    .sync_position(sync_position),.sync_speed(sync_speed),
    .sync_time(sync_time),.busy(),.status(status),.fault(fault),
    .cal_start(),.cal_log_count(),.cal_log_data(),
    .cal_log_elapsed(),.feedback()
  );
  function automatic logic [5:0][31:0] with_axis(
    input logic [5:0][31:0] prior,input int axis,input logic [31:0] value
  );
    with_axis=prior;
    with_axis[axis]=value;
  endfunction
  task automatic restart;
    @(negedge clk); rst_n=0; command=0; engine_done=0;
    repeat(3) @(negedge clk);
    target=REFERENCE;
    speed_time={6{32'h000a_01f4}};
    physical_enabled=1;
    rst_n=1;
    deadline=now_ticks+100;
  endtask
  task automatic submit(input logic [1:0] cmd);
    @(negedge clk); command=cmd;
    @(negedge clk); command=0;
  endtask
  task automatic expect_reject(input int code,input int id);
    int n=0;
    while (!status[1] && n<12) begin
      @(negedge clk);
      if (engine_start && engine_op!=2) $fatal(1,"rejected command emitted WRITE");
      n++;
    end
    if (!status[1] || !status[2] || fault[7:0]!=code ||
        (id!=0 && fault[15:8]!=id))
      $fatal(1,"reject code/id mismatch code=%0d id=%0d status=%h fault=%h",
        code,id,status,fault);
  endtask
  task automatic expect_sync(input int axis,input int goal,input int raw_speed);
    int n=0;
    for (int id=1;id<=6;id++) begin
      n=0;
      while ((!engine_start || engine_op!=2) && n<12) begin
        @(negedge clk); n++;
      end
      if (!engine_start || engine_id!=id || engine_op!=2)
        $fatal(1,"SYNC pre-WRITE live READ missing id=%0d",id);
      @(negedge clk); engine_position=16'(REFERENCE[id-1]); engine_done=1;
      @(negedge clk); engine_done=0;
    end
    n=0;
    while (!engine_start && n<12) begin @(negedge clk); n++; end
    if (!engine_start || engine_op!=10 || sync_position[axis]!=goal ||
        sync_speed[axis]!=raw_speed || sync_time[axis]!=10)
      $fatal(1,"valid SYNC descriptor mismatch axis=%0d goal=%0d speed=%0d start=%0b op=%0d got_goal=%0d got_speed=%0d got_time=%0d status=%h fault=%h invalid=%0d params=%h/%h/%h/%h/%h/%h max=%0d port0=%h condition=%0b",
        axis+1,goal,raw_speed,engine_start,engine_op,sync_position[axis],
        sync_speed[axis],sync_time[axis],status,fault,dut.invalid_speed_axis,
        speed_time[0],speed_time[1],speed_time[2],speed_time[3],
        speed_time[4],speed_time[5],dut.SPEED_MAX_RAW,dut.speed_time[0],
        (speed_time[0][15:0]==0 || speed_time[0][15:0]>dut.SPEED_MAX_RAW));
  endtask
  initial begin
    if (CALIBRATED_MASK!=6'h3f || SPEED_MAX_RAW!=1500)
      $fatal(1,"board calibration constants wrong");
    for(int axis=0;axis<6;axis++) begin
      if (SAFE_MIN[axis]>REFERENCE[axis] || REFERENCE[axis]>SAFE_MAX[axis])
        $fatal(1,"home outside measured limits id=%0d",axis+1);
      restart(); target=with_axis(target,axis,SAFE_MIN[axis]); submit(1);
      expect_sync(axis,int'(SAFE_MIN[axis]),500);
      restart(); target=with_axis(target,axis,SAFE_MAX[axis]); submit(1);
      expect_sync(axis,int'(SAFE_MAX[axis]),500);
      if (SAFE_MIN[axis]>0) begin
        restart(); target=with_axis(target,axis,SAFE_MIN[axis]-1); submit(1);
        expect_reject(12,axis+1);
      end
      restart(); target=with_axis(target,axis,SAFE_MAX[axis]+1); submit(1);
      expect_reject(12,axis+1);
    end
    for(int raw_speed=0;raw_speed<=1501;raw_speed+=
        (raw_speed==0 ? 500 : raw_speed==500 ? 1000 : 1)) begin
      restart(); speed_time=with_axis(speed_time,3,{16'd10,16'(raw_speed)}); submit(1);
      if (raw_speed==0 || raw_speed==1501) expect_reject(15,4);
      else expect_sync(3,int'(REFERENCE[3]),raw_speed);
    end
    restart(); physical_enabled=0; submit(1); expect_reject(1,0);
    // ID 2 starts at its lower boundary; a -1 calibration step must not WRITE.
    restart(); axis_id=2; delta_raw=32'hffff_ffff; submit(2);
    if (engine_op!=2 || !engine_start) begin
      @(negedge clk);
      if (engine_op!=2 || !engine_start) $fatal(1,"calibration READ absent");
    end
    @(negedge clk); engine_position=16'd861; engine_done=1;
    @(negedge clk); engine_done=0;
    expect_reject(12,2);
    $display("TB_G2_BOARD_LIMITS_PASS"); $finish;
  end
endmodule
