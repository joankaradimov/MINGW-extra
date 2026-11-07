cmake_minimum_required(VERSION 3.16)
project(test-link CXX)

find_package(AbletonLink REQUIRED)

add_executable(test-link test-link.cpp)
target_link_libraries(test-link PRIVATE Ableton::Link)
