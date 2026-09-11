#include "rtcs_registers.hpp"

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <cstring>

namespace {
// 参数检查独立封装，避免后续硬件访问路径绕过安全的 dry-run 入口。
void print_usage(const char* program) {
  std::cerr << "usage: " << program << " --dry-run\n";
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 2 || std::strcmp(argv[1], "--dry-run") != 0) {
    print_usage(argv[0]);
    return EXIT_FAILURE;
  }

  // 当前故意不映射 /dev/uio。UIO 设备节点、物理基地址、中断连线与安全互锁
  // 都必须在板级集成阶段确认；因此本程序现阶段只输出 ABI 信息。
  std::cout << "RTCS PS control skeleton\n"
            << "register ABI: 0x" << std::hex << rtcs::kIdVersion << std::dec << "\n"
            << "axes: " << rtcs::kAxisCount << "\n"
            << "state: dry-run; no hardware output is enabled\n";
  return EXIT_SUCCESS;
}
