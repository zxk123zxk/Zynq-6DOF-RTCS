#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtcs {
// PL 返回的接口标识；启动时应先读取并校验，避免使用不匹配的寄存器布局。
// 09：保留 ID 1 参数化运动，新增六轴描述符、标定、反馈与停止寄存器。
constexpr std::uint32_t kIdVersion = 0x5254'000eU;
constexpr std::size_t kAxisCount = 6;
constexpr std::uintptr_t kAxiBaseAddress = 0x43C0'0000U;
constexpr std::size_t kAxiRegionBytes = 0x1'0000U;

// 相对 rtcs_top AXI 基地址的 32 位寄存器偏移。
enum class Reg : std::uint32_t {
  kIdVersion = 0x00,
  kControl = 0x04,
  kCommand = 0x08,
  kStatus = 0x0c,
  kIrqStatus = 0x10,
  kTicksLo = 0x14,
  kTicksHi = 0x18,
  kTarget0 = 0x20,
  kProfileSpeed = 0x38,
  kProfileAccel = 0x3c,
  kDeadlineLo = 0x40,
  kDeadlineHi = 0x44,
  kServoConfig = 0x48,
  kDebug = 0x4c,
  kG1Id = 0x50,
  kG1Op = 0x54,
  kG1Cmd = 0x58,
  kG1Status = 0x5c,
  kG1Result = 0x60,
  kG1Fault = 0x64,
  kG2Id = 0x68,
  kG2ExpectStart = 0x6c,  // 六轴标定步差；单轴容差与观察期
  kG2Target = 0x70,
  kG2SpeedTime = 0x74,
  kG2DeadlineLo = 0x78,
  kG2DeadlineHi = 0x7c,
  kG2Cmd = 0x80,
  kG2Status = 0x84,
  kG2Fault = 0x88,
  kG2Feedback = 0x8c,
  kG2SixParam0 = 0x90,
  kG2SixFeedback0 = 0xa8,
  kG2SixStatus = 0xc0,
  kG2SixFault = 0xc4,
  kG2SixCmd = 0xc8,
  kG2SixDeadlineLo = 0xcc,
  kG2SixDeadlineHi = 0xd0,
  kG2SixCalStart = 0xd4,
  kG2SixCalMask = 0xd8,
  kG2SixLogCount = 0xdc,
  kG2SixLogIndex = 0xe0,
  kG2SixLogData = 0xe4,
  kG2SixLogElapsed = 0xe8,
  kG2LimitId = 0xec,
  kG2LimitMin = 0xf0,
  kG2LimitMax = 0xf4,
  kG2LimitReference = 0xf8,
  kG2LimitSpeedMax = 0xfc,
  kG2SixTolerance = 0x100,
  kG2SixObserve100ms = 0x104,
  kG2SixStart = 0x108,
  kG2SixResult = 0x10c,
  kG2SixDiag = 0x110, // ERROR[23:16], phase[15:8], engine fault[3:0]
  kG2Start = 0x114, // ABI 14 保留地址，绝对运动读值为 0
};

constexpr std::uint32_t kControlEnable = 1U << 0;
constexpr std::uint32_t kControlSoftStop = 1U << 2;
constexpr std::uint32_t kCommandEnqueue = 1U << 0;
constexpr std::uint32_t kG1Ping = 1U;
constexpr std::uint32_t kG1ReadPosition = 2U;
constexpr std::uint32_t kG1ReadTorque = 11U;
// G1 路径只放行 1/2/9/11。位置类写入（3=旧位置写、8=扭矩+目标位置）只能由
// G2 状态机发起；经 G1 路径提交会被 PL 以 fault 13 拒绝。
constexpr std::uint32_t kG1TorqueOff = 9U;
constexpr std::uint32_t kG1Start = 1U;
constexpr std::uint32_t kG1Clear = 2U;
constexpr std::uint32_t kG1Busy = 1U << 0;
constexpr std::uint32_t kG1Done = 1U << 1;
constexpr std::uint32_t kG1Error = 1U << 2;
constexpr std::uint32_t kG1PhysicalTxDisabled = 1U << 3;
constexpr std::uint32_t kG2WriteSent = 1U << 4;
constexpr std::uint32_t kG2Late = 1U << 5;
// ABI 14 单轴绝对命令不采起点：G2_STATUS bit 6 / bit 17 恒为 0。

// PS 在写入 COMMAND.ENQUEUE 前准备好的完整六轴运动描述符。
struct MotionDescriptor {
  std::array<std::int32_t, kAxisCount> target{};
  std::uint32_t speed{};
  std::uint32_t accel{};
  std::uint64_t deadline_ticks{};
  std::uint16_t sequence{};
};

// ABI 14 MMIO 六轴广播描述符；限位仍由 PL 综合常量独立裁决。
struct SixAxisMotionDescriptor {
  std::array<std::uint16_t, kAxisCount> target{};
  std::array<std::uint16_t, kAxisCount> speed_raw{};
  std::array<std::uint16_t, kAxisCount> time_raw{};
  std::uint64_t deadline_ticks{};
};
}  // namespace rtcs
