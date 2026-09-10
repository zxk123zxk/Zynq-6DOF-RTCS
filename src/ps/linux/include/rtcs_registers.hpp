#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtcs {
constexpr std::uint32_t kIdVersion = 0x5254'0001U;
constexpr std::size_t kAxisCount = 6;

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

struct MotionDescriptor {
  std::array<std::int32_t, kAxisCount> target{};
  std::uint32_t speed{};
  std::uint32_t accel{};
  std::uint64_t deadline_ticks{};
  std::uint16_t sequence{};
};
}  // namespace rtcs
