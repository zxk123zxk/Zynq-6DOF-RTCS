`timescale 1ns / 1ps
module tb_g2_descriptor_guard;
  logic clk = 0, rst_n = 0, commit = 0;
  logic [5:0][31:0] target, safe_min, safe_max;
  logic [31:0] speed = 10, accel = 20;
  logic [63:0] deadline = 200, now_ticks = 100;
  logic [5:0] calibrated = 0;
  logic inhibit = 0;
  wire accepted, rejected;
  wire [2:0] reject_code;
  wire [5:0][31:0] snapshot_target;
  wire [31:0] snapshot_speed, snapshot_accel;
  wire [63:0] snapshot_deadline;
  always #5 clk = ~clk;

  g2_descriptor_guard dut (
    .clk(clk), .rst_n(rst_n), .commit(commit), .target(target),
    .speed(speed), .accel(accel), .deadline(deadline), .now_ticks(now_ticks),
    .calibrated(calibrated), .safe_min(safe_min), .safe_max(safe_max),
    .inhibit(inhibit),
    .accepted(accepted), .rejected(rejected), .reject_code(reject_code),
    .snapshot_target(snapshot_target), .snapshot_speed(snapshot_speed),
    .snapshot_accel(snapshot_accel), .snapshot_deadline(snapshot_deadline)
  );

  task automatic submit(input string stage, input logic expected_accept, input logic [2:0] expected_code);
    @(negedge clk); commit = 1;
    @(posedge clk); #1;
    if (accepted !== expected_accept || rejected !== !expected_accept ||
        reject_code !== expected_code)
      $fatal(1, "%s commit response mismatch: accepted=%b rejected=%b code=%d",
             stage, accepted, rejected, reject_code);
    @(negedge clk); commit = 0;
    @(posedge clk); #1;
    if (accepted || rejected) $fatal(1, "commit response must be one cycle");
  endtask

  initial begin
    for (int axis = 0; axis < 6; axis++) begin
      target[axis] = 32'(100 + axis);
      safe_min[axis] = 50;
      safe_max[axis] = 150;
    end
    repeat (3) @(negedge clk); rst_n = 1;
    submit("uncalibrated", 0, 1); // no fabricated calibration
    for (int axis = 0; axis < 6; axis++)
      if (snapshot_target[axis] !== 0) $fatal(1, "rejected command changed snapshot");

    calibrated = 6'h3f;
    submit("valid", 1, 0);
    if (snapshot_speed !== 10 || snapshot_accel !== 20 || snapshot_deadline !== 200)
      $fatal(1, "atomic scalar snapshot mismatch");
    for (int axis = 0; axis < 6; axis++)
      if (snapshot_target[axis] !== 32'(100 + axis))
        $fatal(1, "atomic axis snapshot mismatch");
    for (int axis = 0; axis < 6; axis++) target[axis] = 0;
    speed = 999; accel = 999; deadline = 999;
    @(posedge clk); #1;
    if (snapshot_target[5] !== 105 || snapshot_speed !== 10 || snapshot_deadline !== 200)
      $fatal(1, "snapshot changed after source changed");

    target[5] = 151;
    submit("out_of_range", 0, 4); // one axis out of range rejects whole descriptor
    if (snapshot_target[5] !== 105) $fatal(1, "limit reject changed snapshot");
    target[5] = 105;
    safe_min[2] = 160;
    submit("invalid_calibration_range", 0, 4); // invalid calibration range also rejects
    safe_min[2] = 50;
    inhibit = 1;
    submit("inhibit", 0, 2);
    inhibit = 0; now_ticks = 999;
    submit("expired", 0, 3);
    $display("TB_G2_DESCRIPTOR_GUARD_PASS");
    $finish;
  end
endmodule
