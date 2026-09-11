#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtcs {
// PL 返回的接口标识；启动时应先读取并校验，避免使用不匹配的寄存器布局。
constexpr std::uint32_t kIdVersion = 0x5254'0001U;
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
};

constexpr std::uint32_t kControlEnable = 1U << 0;
constexpr std::uint32_t kControlClearFault = 1U << 1;
constexpr std::uint32_t kControlSoftStop = 1U << 2;
constexpr std::uint32_t kCommandEnqueue = 1U << 0;

// PS 在写入 COMMAND.ENQUEUE 前准备好的完整六轴运动描述符。
struct MotionDescriptor {
  std::array<std::int32_t, kAxisCount> target{};
  std::uint32_t speed{};
  std::uint32_t accel{};
  std::uint64_t deadline_ticks{};
  std::uint16_t sequence{};
};
}  // namespace rtcs
