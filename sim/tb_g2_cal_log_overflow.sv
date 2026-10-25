`timescale 1ns/1ps
module tb_g2_cal_log_overflow;
  logic clk=0,rst_n=0;
  logic [63:0] now_ticks=0,deadline=0;
  logic [1:0] command=0;
  logic engine_done=0;
  logic [15:0] engine_position=0;
  logic [7:0] pending_op=0;
  integer pending_cycles=0,write_count=0;
  wire engine_start,busy;
  wire [7:0] engine_id,engine_op;
  wire [31:0] status,fault,cal_start,log_count,log_data,log_elapsed;
  logic [5:0][31:0] target='0,speed_time='0;
  always #5 clk=~clk;
  always @(posedge clk) if (rst_n) now_ticks <= now_ticks+1;
  g2_six_axis_controller #(.CALIBRATED_MASK(6'h3f),
    .SAFE_MIN('0), .SAFE_MAX({6{32'd2000}}),
    .FEEDBACK_INTERVAL_TICKS(0),
    .OBSERVE_TIMEOUT_TICKS(2000)) dut (
    .clk(clk),.rst_n(rst_n),.physical_enabled(1'b1),
    .now_ticks(now_ticks),.deadline(deadline),.command(command),
    .bus_available(1'b1),.axis_id(32'd2),.delta_raw(32'd20),
    .target(target),.speed_time(speed_time),
    .tolerance({6{16'd5}}),.observe_100ms(8'd50),.ignore(12'd0),.result_index(8'd2),
    .engine_done(engine_done),.engine_fault(4'd0),
    .engine_servo_error(8'd0),.engine_position(engine_position),
    .cal_log_index(8'd127),.engine_start(engine_start),.engine_abort(),
    .engine_id(engine_id),.engine_op(engine_op),
    .engine_write_position(),.engine_write_speed(),.engine_write_time(),
    .sync_position(),.sync_speed(),.sync_time(),.busy(busy),
    .status(status),.fault(fault),.cal_start(cal_start),.feedback(),
    .cal_log_count(log_count),.cal_log_data(log_data),
    .cal_log_elapsed(log_elapsed)
  );
  always @(posedge clk) begin
    if (!rst_n) begin
      engine_done<=0; engine_position<=0; pending_cycles<=0;
      pending_op<=0; write_count<=0;
    end else begin
      engine_done<=0;
      if (engine_start) begin
        pending_cycles<=2; pending_op<=engine_op;
        if (engine_op==8) write_count<=write_count+1;
      end else if (pending_cycles>0) begin
        pending_cycles<=pending_cycles-1;
        if (pending_cycles==1) begin
          engine_done<=1;
          if (pending_op==2) engine_position<=16'd1000;
        end
      end
    end
  end
  initial begin
    repeat(5) @(negedge clk); rst_n=1;
    @(negedge clk); deadline=now_ticks+64'd3000; command=2;
    @(negedge clk); command=0;
    for (int n=0;n<3000 && !status[1];n++) @(negedge clk);
    if (!status[1] || !status[2] || fault[7:0]!=14 ||
        log_count[7:0]!=128 || write_count!=1 || !log_data[28] ||
        log_data[15:0]!=1000 || log_elapsed==0)
      $fatal(1,"calibration log overflow did not fail closed");
    $display("TB_G2_CAL_LOG_OVERFLOW_PASS records=%0d",log_count[7:0]);
    $finish;
  end
endmodule
