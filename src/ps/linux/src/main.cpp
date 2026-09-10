#include "rtcs_registers.hpp"

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <cstring>

namespace {
void print_usage(const char* program) {
  std::cerr << "usage: " << program << " --dry-run\n";
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 2 || std::strcmp(argv[1], "--dry-run") != 0) {
    print_usage(argv[0]);
    return EXIT_FAILURE;
  }

  // Intentionally no /dev/uio mapping yet. The UIO node, physical base address,
  // interrupt wiring and safety interlock are board-integration deliverables.
  std::cout << "RTCS PS control skeleton\n"
            << "register ABI: 0x" << std::hex << rtcs::kIdVersion << std::dec << "\n"
            << "axes: " << rtcs::kAxisCount << "\n"
            << "state: dry-run; no hardware output is enabled\n";
  return EXIT_SUCCESS;
}
