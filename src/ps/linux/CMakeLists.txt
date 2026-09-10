cmake_minimum_required(VERSION 3.20)
project(zynq_rtcs_ctl LANGUAGES CXX)

add_executable(zynq_rtcs_ctl src/main.cpp)
target_compile_features(zynq_rtcs_ctl PRIVATE cxx_std_17)
target_include_directories(zynq_rtcs_ctl PRIVATE include)
target_compile_options(zynq_rtcs_ctl PRIVATE -Wall -Wextra -Wpedantic)
