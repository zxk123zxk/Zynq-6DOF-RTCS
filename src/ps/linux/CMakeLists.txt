cmake_minimum_required(VERSION 3.20)
project(zynq_rtcs_ctl LANGUAGES C CXX)

# PS 端仅构建普通 C++ 控制程序；它不会被自动综合为 PL 硬件逻辑。
add_executable(zynq_rtcs_ctl src/main.cpp)
target_compile_features(zynq_rtcs_ctl PRIVATE cxx_std_17)
target_include_directories(zynq_rtcs_ctl PRIVATE include)
target_compile_options(zynq_rtcs_ctl PRIVATE -Wall -Wextra -Wpedantic)

add_executable(rtcs_uart_smoke apps/rtcs_uart_smoke.c)
set_target_properties(rtcs_uart_smoke PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)
target_compile_options(rtcs_uart_smoke PRIVATE -Wall -Wextra -Wpedantic)
