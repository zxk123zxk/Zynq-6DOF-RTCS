`timescale 1ns/1ps
// ABI 08 端到端 G2 用例：0x28=1 与可变目标/时间/速度同帧、G1 路径白名单、
// 无起点门槛、到达确认带、迟到/超时、显式多次提交与取消/禁发语义。
// 这个平台只连一个模拟舵机模型，不接真实总线。
module tb_rtcs_g2_one_servo;
  localparam logic [15:0] LIVE_START = 16'd2026;
  localparam logic [15:0] TARGET = 16'd2080;
  logic clk=0, rst_n=0, estop_n=0, servo_rx=1;
  logic [31:0] awaddr=0,wdata=0,araddr=0;
  logic [3:0] wstrb=0;
  logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
  wire awready,wready,bvalid,arready,rvalid,irq,servo_tx,servo_tx_en;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata;
  logic [7:0] tx_byte;
  wire tx_valid,tx_fault;
  logic [7:0] frame[0:14];
  integer frame_bytes=0,write_count=0,read_count=0,torque_read_count=0,
          torque_on_count=0,torque_off_count=0;
  logic respond=1;
  logic model_updates_on_write=1;
  logic [7:0] model_write_error=0;
  logic [15:0] model_torque=0;         // 舵机侧 0x28，上电为 0
  logic [15:0] model_position=16'd2026;
  logic [15:0] model_settle_position=16'd2080;
  logic [15:0] goal_seen=16'hffff;
  logic [15:0] expected_target=TARGET, expected_speed=16'd50, expected_time=0;
  logic [7:0] expected_id=1;
  logic [7:0] frame_sum;
  logic [63:0] model_arrival_tick=0;
  logic obs_clear=0;
  always #5 clk=~clk;

  rtcs_top #(.G1_TTL_PORTS(1'b1),
    .G2_CALIBRATED_MASK(6'h3f), .G2_SAFE_MIN('0),
    .G2_SAFE_MAX({6{32'd4000}}), .G2_REFERENCE({6{32'd2000}}),
    .G2_RESPONSE_TIMEOUT_TICKS(15_000),
    .G2_FEEDBACK_INTERVAL_TICKS(2_000),
    .G2_OBSERVE_TIMEOUT_TICKS(150_000)) dut (
    .s_axi_aclk(clk),.s_axi_aresetn(rst_n),
    .s_axi_awaddr(awaddr),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
    .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
    .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
    .s_axi_araddr(araddr),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
    .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
    .servo_rx(servo_rx),.servo_tx(servo_tx),.servo_tx_en(servo_tx_en),
    .estop_n(estop_n),.irq(irq)
  );
  uart_byte_rx observer (.clk(clk),.rst_n(rst_n),.clear(obs_clear),.rx(servo_tx),
    .data(tx_byte),.valid(tx_valid),.framing_fault(tx_fault));
  always @(posedge clk) if (rst_n && tx_valid) begin
    if (frame_bytes >= 15) $fatal(1,"frame too long");
    frame[frame_bytes]=tx_byte;
    frame_bytes=frame_bytes+1;
  end
  task automatic dump_frame(input string tag);
    integer i;
    begin
      $display("DUMP %s frame_bytes=%0d time=%0t", tag, frame_bytes, $time);
      for (i=0;i<frame_bytes;i=i+1) $write(" %02x", frame[i]);
      $write("\n");
    end
  endtask
  task automatic torque_status_packet;
    logic [7:0] sum;
    begin
      sum=expected_id+8'd3+model_torque[7:0];
      send_byte(8'hff); send_byte(8'hff); send_byte(expected_id);
      send_byte(8'd3); send_byte(0); send_byte(model_torque[7:0]);
      send_byte(~sum);
    end
  endtask
  // 取消/禁发会把总线帧截断：被截断的帧不是有效帧，观测器必须重新同步，
  // 否则残帧的位相位会污染下一帧的首字节（DUT 侧引擎对残帧本身是故障安全的）。
  task automatic resync_observer;
    @(negedge clk); obs_clear=1;
    repeat (5) @(negedge clk);
    @(negedge clk); obs_clear=0; frame_bytes=0;
    repeat (2) @(negedge clk);
  endtask
  task automatic send_byte(input logic [7:0] value);    @(negedge clk); servo_rx=0; repeat(100) @(negedge clk);
    for (int i=0;i<8;i++) begin servo_rx=value[i]; repeat(100) @(negedge clk); end
    servo_rx=1; repeat(100) @(negedge clk);
  endtask
  task automatic status_packet(input bit is_read,input logic [15:0] pos);
    logic [7:0] sum;
    logic [7:0] error_byte;
    begin
      error_byte=is_read ? 8'd0 : model_write_error;
      sum=expected_id+(is_read?8'd4:8'd2)+error_byte;
      send_byte(8'hff); send_byte(8'hff); send_byte(expected_id);
      send_byte(is_read?8'd4:8'd2); send_byte(error_byte);
      if (is_read) begin
        send_byte(pos[7:0]); send_byte(pos[15:8]);
        sum=sum+pos[7:0]+pos[15:8];
      end
      send_byte(~sum);
    end
  endtask
  // 模拟舵机：只在 PL 释放半双工 TX 之后应答；运动帧必须自带扭矩使能。
  always @(negedge servo_tx_en) if (rst_n && estop_n && frame_bytes>0 && respond) begin
    case (frame[4])
      8'd2: begin // READ 当前位置或只读 0x28
        if (frame_bytes!=8 || frame[0]!=8'hff || frame[1]!=8'hff ||
            frame[2]!=expected_id || frame[3]!=8'd4)
          begin dump_frame("READ"); $fatal(1,"READ frame mismatch"); end
        if (frame[5]==8'h28 && frame[6]==8'd1) begin
          torque_read_count=torque_read_count+1;
          frame_bytes=0;
          if (respond) begin #2000; torque_status_packet(); end
        end else begin
        if (frame[5]!=8'h38 || frame[6]!=8'd2)
          $fatal(1,"READ position address/length mismatch");
        read_count=read_count+1;
        frame_bytes=0;
        if (model_arrival_tick != 0 && dut.hw_ticks >= model_arrival_tick)
          model_position=model_settle_position;
        if (respond) begin #2000; status_packet(1,model_position); end
        end
      end
      8'd1: begin // PING
        if (frame_bytes!=6 || frame[0]!=8'hff || frame[1]!=8'hff ||
            frame[2]!=1 || frame[3]!=8'd2 || frame[5]!=8'hfb)
          $fatal(1,"PING frame mismatch");
        frame_bytes=0;
        if (respond) begin #2000; status_packet(0,0); end
      end
      8'd3: begin // WRITE：起点必须是 0x28，长度区分运动帧与卸力帧
        if (frame[5]!=8'h28) $fatal(1,"WRITE did not start at 0x28");
        if (frame[3]==8'h0b) begin
          frame_sum=0;
          for (int k=2;k<=14;k++) frame_sum=frame_sum+frame[k];
          if (frame_bytes!=15 || frame[0]!=8'hff || frame[1]!=8'hff ||
              frame[2]!=expected_id || frame[4]!=8'd3 || frame[6]!=8'd1 ||
              frame[7]!=8'd0 || frame[8]!=expected_target[7:0] ||
              frame[9]!=expected_target[15:8] ||
              frame[10]!=expected_time[7:0] || frame[11]!=expected_time[15:8] ||
              frame[12]!=expected_speed[7:0] || frame[13]!=expected_speed[15:8] ||
              frame_sum!=8'hff)
            $fatal(1,"ABI 08 torque+position frame mismatch");
          write_count=write_count+1;
          torque_on_count=torque_on_count+1;
          model_torque=1;
          goal_seen={frame[9],frame[8]};
          frame_bytes=0;
          if (model_updates_on_write) model_position=model_settle_position;
          if (respond) begin #2000; status_packet(0,0); end
        end else if (frame[3]==8'd4) begin
          if (frame_bytes!=8 || frame[6]!=8'd0 || frame[7]!=8'hcf)
            $fatal(1,"torque-off frame mismatch");
          torque_off_count=torque_off_count+1;
          model_torque=0;
          frame_bytes=0;
          if (respond) begin #2000; status_packet(0,0); end
        end else $fatal(1,"unexpected WRITE length");
      end
      default: $fatal(1,"unexpected bus instruction");
    endcase
  end
  task automatic wr(input logic [31:0] addr,input logic [31:0] value);
    @(negedge clk); awaddr=addr; wdata=value; wstrb=4'hf; awvalid=1; wvalid=1;
    @(negedge clk); awvalid=0; wvalid=0;
    wait(bvalid); @(negedge clk); bready=1;
    @(negedge clk); bready=0;
  endtask
  task automatic rd(input logic [31:0] addr,output logic [31:0] value);
    @(negedge clk); araddr=addr; arvalid=1;
    @(negedge clk); arvalid=0; wait(rvalid); value=rdata;
    @(negedge clk); rready=1; @(negedge clk); rready=0;
  endtask
  // G1 路径命令（PING / 卸力 / 被拒的操作码）。
  task automatic g1_run(input logic [7:0] op);
    wr('h58,32'd2); wr('h50,32'd1); wr('h54,op); wr('h58,32'd1);
  endtask
  task automatic wait_g1_done(output logic [31:0] status,output logic [31:0] fault);
    integer polls;
    begin
      status=0; fault=0; g1_found=0;
      for (polls=0;polls<100000 && !g1_found;polls++) begin
        @(negedge clk);
        if (dut.g1_status[1]) begin status=dut.g1_status; fault=dut.g1_fault; g1_found=1; end
      end
      if (!g1_found) $fatal(1,"G1 completion timeout");
    end
  endtask
  task automatic descriptor(input logic [31:0] id,expect_pos,target_pos,speed,
                             input logic [63:0] deadline);
    wr('h68,id); wr('h6c,32'h0032_000f); wr('h70,target_pos); wr('h74,speed);
    wr('h78,deadline[31:0]); wr('h7c,deadline[63:32]);
  endtask
  task automatic commit;
    wr('h80,32'h4732_0001);
  endtask
  task automatic wait_done(output logic [31:0] status);
    integer polls;
    begin
      status=0; g2_found=0;
      for (polls=0;polls<500000 && !g2_found;polls++) begin
        @(negedge clk);
        if (dut.g2_status[1]) begin status=dut.g2_status; g2_found=1; end
      end
      if (!g2_found) $fatal(1,"G2 completion timeout");
    end
  endtask
  logic [31:0] st,fault;
  integer before_writes,before_releases;
  logic [63:0] command_deadline;
  logic g1_found=0, g2_found=0, motion_launched=0;
  initial begin
    repeat(5) @(negedge clk); rst_n=1; estop_n=1;

    // ---- G1 路径白名单：只读与卸力放行，位置类写入必须以 fault 13 拒绝 ----
    g1_run(8'd1); wait_g1_done(st,fault);
    if (fault!=0 || st[2] || !st[1]) $fatal(1,"G1 PING was not allowed");
    if (torque_off_count!=0 || write_count!=0) $fatal(1,"PING issued a write");
    reset_result_g1();

    g1_run(8'd9); wait_g1_done(st,fault);
    if (fault!=0 || st[2] || torque_off_count!=1 || write_count!=0)
      $fatal(1,"G1 torque-off was not the only G1 write");
    reset_result_g1();

    before_releases=torque_off_count;
    g1_run(8'd3); wait_g1_done(st,fault);
    if (fault!=13 || !st[2] || frame_bytes!=0 || write_count!=0 ||
        torque_off_count!=before_releases)
      $fatal(1,"removed position-only opcode was not refused on the G1 path");
    reset_result_g1();
    g1_run(8'd8); wait_g1_done(st,fault);
    if (fault!=13 || !st[2] || frame_bytes!=0 || write_count!=0 ||
        torque_off_count!=before_releases)
      $fatal(1,"G1 path could request a motion frame");
    reset_result_g1();

    // ---- 描述符门禁：仅 ID 1..6、16 位目标、有效期限与物理允许。----
    estop_n=0;
    descriptor(1,32'hdead_beef,TARGET,50,64'd1000000);
    commit(); wait_done(st);
    rd('h88,fault); if (fault!=1 || write_count!=0) $fatal(1,"inhibit rejection failed");
    estop_n=1;
    descriptor(7,0,TARGET,50,64'd1000000);
    commit(); wait_done(st);
    rd('h88,fault); if (fault!=3 || write_count!=0) $fatal(1,"ID 7 not rejected");
    descriptor(1,0,32'h0001_0000,50,64'd1000000);
    commit(); wait_done(st);
    rd('h88,fault); if (fault!=3 || write_count!=0) $fatal(1,"wide target not rejected");
    descriptor(1,0,TARGET,50,64'd1);
    commit(); wait_done(st);
    rd('h88,fault); if (fault!=4 || write_count!=0) $fatal(1,"expired deadline accepted");
    descriptor(1,0,TARGET,50,dut.hw_ticks+64'd200100000);
    commit(); wait_done(st);
    rd('h88,fault); if (fault!=4 || write_count!=0) $fatal(1,"long deadline accepted");

    // 极远起点与任意旧 EXPECT 值均不阻止显式运动；帧内 0x28 必须为 1。
    model_position=16'd50000;
    expected_target=TARGET; expected_speed=16'd500; expected_time=16'h1234;
    descriptor(1,32'hdead_beef,TARGET,{16'h1234,16'd500},dut.hw_ticks+64'd120000);
    commit();
    wr('h70,1998); wr('h74,0); // 提交后寄存器变化不能改变已快照的帧。
    wait_done(st);
    if (st[2] || st[5] || st[6] || !st[7] || !st[16] || st[17] ||
        !st[4] || write_count!=1 || read_count!=3 || st[15:8]<3 ||
        goal_seen!=TARGET || model_torque!=1 || torque_on_count!=1)
      $fatal(1,"variable parameters or torque enable failed");

    // 第二次显式提交改变目标，无 PL 复位且不依赖起点。
    expected_target=16'd1998; expected_speed=16'd50; expected_time=0;
    model_settle_position=expected_target;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd120000);
    commit(); wait_done(st);
    if (st[2] || !st[4] || write_count!=2 || goal_seen!=expected_target)
      $fatal(1,"second explicit move was not accepted");

    // 终点误差边界：+15 通过，+16 经有限观察后报 fault 9。
    expected_target=16'd2100;
    model_settle_position=16'd2115;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd120000);
    commit(); wait_done(st);
    if (st[2] || !st[4] || write_count!=3) $fatal(1,"+15 feedback was rejected");
    model_settle_position=16'd2116;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd120000);
    commit(); wait_done(st);
    rd('h88,fault);
    if (fault!=9 || !st[2] || write_count!=4)
      $fatal(1,"+16 feedback was accepted or timeout unbounded");

    // 第三次到位反馈越过原期限，但在有限观察期内，仍按到位成功。
    model_updates_on_write=0;
    model_position=16'd1800;
    model_settle_position=expected_target;
    command_deadline=dut.hw_ticks+64'd40000;
    model_arrival_tick=command_deadline+64'd10000;
    descriptor(1,0,expected_target,50,command_deadline);
    commit(); wait_done(st);
    rd('h88,fault);
    if (fault!=0 || !st[5] || !st[1] || st[2] || !st[4] || write_count!=5)
      $fatal(1,"late feedback did not count as final arrival");

    // 到观察期仍未到位：只发送一帧，不自动补发。
    model_arrival_tick=0; model_position=16'd1800;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd40000);
    commit(); wait_done(st);
    rd('h88,fault);
    if (fault!=9 || st[5] || write_count!=6)
      $fatal(1,"observation timeout or no-retry guarantee failed");

    // WRITE 启动后撤掉物理允许：立即三态，随后仍可由新命令显式重试。
    before_writes=write_count;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd120000);
    commit();
    begin
      motion_launched=0;
      for (int polls=0;polls<100000 && !motion_launched;polls++) begin
        @(negedge clk);
        if (dut.g2_write_sent) motion_launched=1;
      end
      if (!motion_launched) $fatal(1,"motion frame did not launch");
    end
    estop_n=0;
    repeat(10) @(negedge clk);
    if (servo_tx_en || write_count!=before_writes)
      $fatal(1,"physical inhibit failed to abort the frame");
    estop_n=1;
    resync_observer();
    model_updates_on_write=1; model_settle_position=expected_target;
    descriptor(1,0,expected_target,50,dut.hw_ticks+64'd120000);
    commit(); wait_done(st);
    if (st[2] || write_count!=before_writes+1)
      $fatal(1,"explicit command after inhibit failed");

    // 卸力只写 0x28<-0，不产生位置帧。
    before_releases=torque_off_count;
    before_writes=write_count;
    g1_run(8'd9); wait_g1_done(st,fault);
    if (fault!=0 || torque_off_count!=before_releases+1 || model_torque!=0 ||
        write_count!=before_writes)
      $fatal(1,"release did not clear only the torque switch");
    reset_result_g1();
    g1_run(8'd11); wait_g1_done(st,fault);
    rd('h60,st);
    if (fault!=0 || st[7:0]!=0 || torque_read_count!=1 ||
        write_count!=before_writes)
      $fatal(1,"read-only torque status did not return 0");
    reset_result_g1();

    // 手动单轴路径独立允许 ID 2..6；逐个核对实际单播 ID、扭矩和目标帧。
    for (int axis=2;axis<=6;axis++) begin
      expected_id=8'(axis); expected_target=16'(2000+axis);
      expected_speed=16'd1500; expected_time=16'd10;
      model_settle_position=expected_target;
      before_writes=write_count;
      descriptor(axis,0,expected_target,{16'd10,16'd1500},
                 dut.hw_ticks+64'd120000);
      commit(); wait_done(st);
      if (st[2] || write_count!=before_writes+1 || goal_seen!=expected_target)
        $fatal(1,"ID %0d single-axis motion failed",axis);
    end

    // 绝对目标只按发后反馈判断：误差 25 可通过，已在带内且未变化也可通过。
    expected_id=1; expected_target=2100; expected_speed=500; expected_time=10;
    model_position=2000; model_settle_position=2125; model_updates_on_write=1;
    descriptor(1,0,2100,{16'd10,16'd500},dut.hw_ticks+64'd120000);
    wr('h6c,32'h0032_001e);
    commit(); wait_done(st);
    if (st[2] || st[17] || !st[16] || st[6] || !st[7])
      $fatal(1,"configurable tolerance rejected valid feedback");
    expected_target=2120; model_position=2100; model_updates_on_write=0;
    descriptor(1,0,2120,{16'd10,16'd500},dut.hw_ticks+64'd120000);
    wr('h6c,32'h0032_001e);
    commit(); wait_done(st); rd('h88,fault);
    if (fault!=0 || st[2] || !st[4] || !st[7] || st[17])
      $fatal(1,"valid in-band absolute feedback was rejected");

    // Reproduce the ABI 0D report at the protocol boundary: the frame is
    // emitted once, but a checksum-valid nonzero servo ERROR is not an ACK.
    expected_id=5; expected_speed=500; expected_time=100;
    model_updates_on_write=0; model_write_error=8'h10;
    expected_target=1500; model_position=2012;
    before_writes=write_count;
    descriptor(5,0,1500,{16'd100,16'd500},dut.hw_ticks+64'd120000);
    commit(); wait_done(st); rd('h88,fault);
    if (fault!=8 || !st[2] || !st[4] || st[16] || st[7] ||
        write_count!=before_writes+1 || dut.g1_fault!=8 ||
        dut.g1_result!=32'h0010_0000)
      $fatal(1,"ID 5 WRITE ERROR was hidden, accepted, or retried");

    model_write_error=0; model_updates_on_write=1;
    expected_target=2000; model_position=1931; model_settle_position=1989;
    descriptor(5,0,2000,{16'd100,16'd500},dut.hw_ticks+64'd120000);
    commit(); wait_done(st); rd('h88,fault);
    if (fault!=0 || st[2] || !st[4] || !st[16] || !st[7] ||
        write_count!=before_writes+2)
      $fatal(1,"ID 5 explicit recovery after rejected target failed");

    model_write_error=8'h10; model_updates_on_write=0;
    expected_target=1000;
    descriptor(5,0,1000,{16'd100,16'd500},dut.hw_ticks+64'd120000);
    commit(); wait_done(st); rd('h88,fault);
    if (fault!=8 || !st[2] || !st[4] || st[16] || st[7] ||
        write_count!=before_writes+3 || dut.g1_result!=32'h0010_0000)
      $fatal(1,"second ID 5 WRITE ERROR was hidden or accepted");

    $display("TB_RTCS_G2_ONE_SERVO_PASS reads=%0d motion_frames=%0d torque_on=%0d releases=%0d",
      read_count,write_count,torque_on_count,torque_off_count);
    $finish;
  end
  // G1 结果在下一个命令前由软件清除，这里模拟同一动作。
  task automatic reset_result_g1;
    wr('h58,32'd2);
    repeat(2) @(negedge clk);
    if (dut.g1_status[1] || dut.g1_status[2])
      $fatal(1,"G1 clear did not drop done/error");
  endtask
endmodule
