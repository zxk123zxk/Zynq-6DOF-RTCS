`ifndef RTCS_PKG_SV
`define RTCS_PKG_SV
package rtcs_pkg;
  // 系统固定为六关节；PS 与 PL 必须使用相同的轴数量。
  parameter int unsigned AXIS_COUNT = 6;
  // 供软件启动时确认已连接到兼容版本的 PL 外设。
  // 08：G2 目标/原始速度/原始时间由描述符提供，无起点窗；到位带 ±15。
  //     同一运动帧仍写 0x28=1。寄存器地址布局相对 07 不变。
  // 09：逐轴现场小步标定、六轴广播路径及独立反馈寄存器。
  // 0A：标定目标 ±5、逐条反馈日志、0x28 只读诊断及 ID 1..6 手动单轴。
  // 0B：实测六轴闭区间、原始速度上限和只读限位诊断。
  // 0C：命令结果独立化、可配置容差/观察期、起点及故障阶段诊断。
  // 0D：六轴诊断寄存器 [23:16] 锁存故障应答的舵机 ERROR 原始字节。
  // 0E：绝对单轴/六轴直接 WRITE；起点有效位不再是绝对运动的前提。
  parameter logic [31:0] ID_VERSION = 32'h5254_000e;

  // AXI4-Lite 寄存器字节偏移：与 PS 端 rtcs_registers.hpp 保持一致。
  localparam logic [7:0] REG_ID_VERSION    = 8'h00;
  localparam logic [7:0] REG_CONTROL       = 8'h04;
  localparam logic [7:0] REG_COMMAND       = 8'h08;
  localparam logic [7:0] REG_STATUS        = 8'h0c;
  localparam logic [7:0] REG_IRQ_STATUS    = 8'h10;
  localparam logic [7:0] REG_TICKS_LO      = 8'h14;
  localparam logic [7:0] REG_TICKS_HI      = 8'h18;
  localparam logic [7:0] REG_TARGET0       = 8'h20;
  localparam logic [7:0] REG_PROFILE_SPEED = 8'h38;
  localparam logic [7:0] REG_PROFILE_ACCEL = 8'h3c;
  localparam logic [7:0] REG_DEADLINE_LO   = 8'h40;
  localparam logic [7:0] REG_DEADLINE_HI   = 8'h44;
  localparam logic [7:0] REG_SERVO_CONFIG  = 8'h48;
  localparam logic [7:0] REG_DEBUG         = 8'h4c;
  localparam logic [7:0] REG_G1_ID         = 8'h50;
  localparam logic [7:0] REG_G1_OP         = 8'h54;
  localparam logic [7:0] REG_G1_CMD        = 8'h58;
  localparam logic [7:0] REG_G1_STATUS     = 8'h5c;
  localparam logic [7:0] REG_G1_RESULT     = 8'h60;
  localparam logic [7:0] REG_G1_FAULT      = 8'h64;
  localparam logic [7:0] REG_G2_ID         = 8'h68;
  localparam logic [8:0] REG_G2_EXPECT     = 9'h06c; // 六轴标定步差；单轴 tol[15:0], observe_100ms[31:16]
  localparam logic [7:0] REG_G2_TARGET     = 8'h70;
  localparam logic [7:0] REG_G2_SPEED_TIME = 8'h74;
  localparam logic [7:0] REG_G2_DEADLINE_LO = 8'h78;
  localparam logic [7:0] REG_G2_DEADLINE_HI = 8'h7c;
  localparam logic [7:0] REG_G2_CMD        = 8'h80;
  localparam logic [7:0] REG_G2_STATUS     = 8'h84;
  localparam logic [7:0] REG_G2_FAULT      = 8'h88;
  localparam logic [7:0] REG_G2_FEEDBACK   = 8'h8c;
  localparam logic [7:0] REG_G2_SIX_PARAM0 = 8'h90; // 每轴 time[31:16], speed[15:0]
  localparam logic [7:0] REG_G2_SIX_FEEDBACK0 = 8'ha8;
  localparam logic [7:0] REG_G2_SIX_STATUS = 8'hc0;
  localparam logic [7:0] REG_G2_SIX_FAULT = 8'hc4;
  localparam logic [7:0] REG_G2_SIX_CMD = 8'hc8; // 1=sync, 2=calibrate-step, 3=stop
  localparam logic [7:0] REG_G2_SIX_DEADLINE_LO = 8'hcc;
  localparam logic [7:0] REG_G2_SIX_DEADLINE_HI = 8'hd0;
  localparam logic [7:0] REG_G2_SIX_CAL_START = 8'hd4;
  localparam logic [7:0] REG_G2_SIX_CAL_MASK = 8'hd8; // 编译期实测限位掩码，只读
  localparam logic [7:0] REG_G2_SIX_LOG_COUNT = 8'hdc;
  localparam logic [7:0] REG_G2_SIX_LOG_INDEX = 8'he0;
  localparam logic [7:0] REG_G2_SIX_LOG_DATA = 8'he4;
  localparam logic [7:0] REG_G2_SIX_LOG_ELAPSED = 8'he8;
  localparam logic [7:0] REG_G2_LIMIT_ID = 8'hec;
  localparam logic [7:0] REG_G2_LIMIT_MIN = 8'hf0;
  localparam logic [7:0] REG_G2_LIMIT_MAX = 8'hf4;
  localparam logic [7:0] REG_G2_LIMIT_REFERENCE = 8'hf8;
  localparam logic [7:0] REG_G2_LIMIT_SPEED_MAX = 8'hfc;
  localparam logic [8:0] REG_G2_SIX_TOLERANCE = 9'h100; // LIMIT_ID 选轴，1..100 count
  localparam logic [8:0] REG_G2_SIX_OBSERVE = 9'h104; // 10..100，单位 100 ms
  localparam logic [8:0] REG_G2_SIX_START = 9'h108; // LIMIT_ID 选轴，现场预读
  localparam logic [8:0] REG_G2_SIX_RESULT = 9'h10c; // 起点有效/反馈有效/位置变化掩码
  localparam logic [8:0] REG_G2_SIX_DIAG = 9'h110; // ERROR[23:16]、阶段[15:8]、引擎故障[3:0]
  localparam logic [8:0] REG_G2_START = 9'h114; // ABI 0E 保留地址，绝对运动读值为 0
  // 单轴 G2 故障锁存（0E 增量，只读，不改动任何既有寄存器语义，因此不升 ABI）：
  //   [23:16] 故障应答里的舵机 ERROR 原始字节（0x41 状态）
  //   [15:8]  发生阶段 1=提交后待发 2=发送/等待写应答 3=发后反馈
  //   [7:4]   故障轴 ID
  //   [3:0]   引擎故障码：3 应答超时 4 长度不符 5 停止位 6 应答ID不符 7 校验和 8 舵机ERROR非零
  // 没有它时，rtcs_top 会把写阶段的全部引擎故障压成 G2 fault=8，操作者无法区分
  // “舵机报了角度类错误”与“根本没收到应答/收到坏帧”。旧 PL 读该地址返回 0。
  localparam logic [8:0] REG_G2_DIAG = 9'h118; // G2 单轴故障锁存，只读
endpackage
`endif
