```cmake
# ----------------------------------------------------------------------------------------------------------------------
# HoloCanvas :: shared :: CMake build configuration
#
# This CMakeLists.txt drives the compilation of the reusable “shared” component that is linked into all HoloCanvas
# micro-services.  It bundles common primitives such as:
#   • cryptographic helpers (OpenSSL wrappers)
#   • binary-safe serialization utilities (Protocol-Buffers / gRPC)
#   • event-stream abstractions (Kafka)
#   • state-machine helpers
#   • common error/ logging facilities
#
# The file is intentionally opinionated and enables modern-C best practices out of the box: C11, LTO, enable-all-warnings,
# sanitizers, unit-tests, documentation, packaging, and export-targets for downstream consumers.
# ----------------------------------------------------------------------------------------------------------------------

cmake_minimum_required(VERSION 3.20 FATAL_ERROR)

# 1. Project basics ---------------------------------------------------------------------
project(
    HoloCanvasShared
    VERSION 0.3.0
    DESCRIPTION "Common runtime & utils for the HoloCanvas micro-gallery blockchain (NFT)"
    LANGUAGES C
)

# 2. Build options ----------------------------------------------------------------------
option(BUILD_SHARED_LIBS "Build shared libraries instead of static ones" ON)
option(ENABLE_SANITIZER  "Enable UBSan / ASan checks (Debug only)"       OFF)
option(ENABLE_LTO        "Enable Link-Time-Optimization (Release only)" ON)
option(ENABLE_TESTS      "Build unit tests with CTest / Catch2"          ON)
option(ENABLE_COVERAGE   "Enable gcov/llvm-cov instrumentation"          OFF)

# 3. Toolchain sanity checks ------------------------------------------------------------
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR
        "In-source builds are disabled. Please create a separate build directory:\n"
        "  mkdir build && cd build && cmake .."
    )
endif()

# 4. Compiler setup ---------------------------------------------------------------------
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

function(holo_enable_all_warnings TARGET)
    if (MSVC)
        target_compile_options(${TARGET} PRIVATE /W4 /WX)
    else()
        target_compile_options(${TARGET} PRIVATE
            -Wall -Wextra -Wpedantic -Werror
            -Wshadow -Wpointer-arith -Wcast-align
            -Wstrict-prototypes -Wmissing-prototypes
            -Wwrite-strings -Wconversion
        )
    endif()
endfunction()

# 5. External dependencies --------------------------------------------------------------
find_package(Threads       REQUIRED)
find_package(OpenSSL       REQUIRED)
find_package(Protobuf      REQUIRED)
find_package(gRPC          REQUIRED)
find_package(ZLIB          REQUIRED)
# Kafka client (librdkafka) is shipped as a submodule
add_subdirectory(third_party/librdkafka EXCLUDE_FROM_ALL)

# 6. Source layout ----------------------------------------------------------------------
file(GLOB_RECURSE HOLOCANVAS_SHARED_SRC  CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c"
)

file(GLOB_RECURSE HOLOCANVAS_SHARED_HEADERS CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/include/*.h"
)

# 7. Auto-generate a version header -----------------------------------------------------
set(GIT_DESCRIBE "unknown")
find_package(Git QUIET)
if(GIT_FOUND)
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" -C "${CMAKE_CURRENT_SOURCE_DIR}" describe --tags --always --dirty
        OUTPUT_VARIABLE GIT_DESCRIBE
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()

configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/version.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/hc_version.h"
    @ONLY
)

# 8. Library target ---------------------------------------------------------------------
add_library(hc_shared ${HOLOCANVAS_SHARED_SRC} ${HOLOCANVAS_SHARED_HEADERS})
add_library(HoloCanvas::Shared ALIAS hc_shared)

target_include_directories(hc_shared
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(hc_shared
    PUBLIC
        OpenSSL::SSL
        OpenSSL::Crypto
        Threads::Threads
        ZLIB::ZLIB
        Protobuf::protobuf
        gRPC::grpc
    PRIVATE
        rdkafka
)

holo_enable_all_warnings(hc_shared)

target_compile_definitions(hc_shared
    PUBLIC
        $<$<CONFIG:Debug>:HC_DEBUG=1>
        HC_VERSION=\"${PROJECT_VERSION}\"
        HC_GIT_DESCRIBE=\"${GIT_DESCRIBE}\"
)

# 8.1 Sanitizers ------------------------------------------------------------------------
if(ENABLE_SANITIZER AND CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(hc_shared PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options  (hc_shared PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

# 8.2 LTO ------------------------------------------------------------------------------
include(CheckIPOSupported)
if(ENABLE_LTO)
    check_ipo_supported(RESULT LTO_OK)
    if(LTO_OK)
        message(STATUS "Enabling LTO")
        set_property(TARGET hc_shared PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
    endif()
endif()

# 8.3 Coverage --------------------------------------------------------------------------
if(ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(hc_shared PUBLIC -O0 -g --coverage)
    target_link_options  (hc_shared PUBLIC --coverage)
endif()

# 9. Installation -----------------------------------------------------------------------
include(GNUInstallDirs)
install(
    TARGETS hc_shared
    EXPORT  HoloCanvasSharedTargets
    ARCHIVE  DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY  DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME  DESTINATION ${CMAKE_INSTALL_BINDIR}
)

install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
    FILES_MATCHING PATTERN "*.h"
)

install(
    FILES "${CMAKE_CURRENT_BINARY_DIR}/generated/hc_version.h"
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/holocanvas
)

install(
    EXPORT HoloCanvasSharedTargets
    NAMESPACE HoloCanvas::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/HoloCanvas
)

include(CMakePackageConfigHelpers)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/HoloCanvasSharedConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/HoloCanvasSharedConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/HoloCanvasSharedConfig.cmake"
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/HoloCanvas
)

install(
    FILES
        "${CMAKE_CURRENT_BINARY_DIR}/HoloCanvasSharedConfig.cmake"
        "${CMAKE_CURRENT_BINARY_DIR}/HoloCanvasSharedConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/HoloCanvas
)

# 10. Testing ---------------------------------------------------------------------------
if(ENABLE_TESTS)
    enable_testing()
    add_subdirectory(test)
endif()

# 11. Developer helpers -----------------------------------------------------------------
# clang-format target -------------------------------------------------------------------
find_program(CLANG_FORMAT_EXE NAMES clang-format)
if(CLANG_FORMAT_EXE)
    file(GLOB_RECURSE C_SOURCES_CLANGFORMAT
         "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c"
         "${CMAKE_CURRENT_SOURCE_DIR}/include/*.h"
    )
    add_custom_target(
        clang-format
        COMMAND ${CLANG_FORMAT_EXE} -i ${C_SOURCES_CLANGFORMAT}
        COMMENT "Running clang-format on source tree"
    )
endif()

# cppcheck / static-analysis -------------------------------------------------------------
find_program(CPPCHECK_EXE NAMES cppcheck)
if(CPPCHECK_EXE)
    add_custom_target(
        static-analysis
        COMMAND ${CPPCHECK_EXE} --enable=all --inconclusive --force
                --language=c --std=c11
                -I ${CMAKE_CURRENT_SOURCE_DIR}/include
                ${HOLOCANVAS_SHARED_SRC}
        COMMENT "Running CppCheck analysis"
    )
endif()

# 12. Summary ----------------------------------------------------------------------------
message(STATUS "----------------------------------------------------------------------")
message(STATUS "HoloCanvas::Shared Configuration:")
message(STATUS "  Build type           : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Install prefix       : ${CMAKE_INSTALL_PREFIX}")
message(STATUS "  Git describe         : ${GIT_DESCRIBE}")
message(STATUS "  Sanitizer enabled    : ${ENABLE_SANITIZER}")
message(STATUS "  LTO enabled          : ${ENABLE_LTO}")
message(STATUS "  Coverage enabled     : ${ENABLE_COVERAGE}")
message(STATUS "  Tests enabled        : ${ENABLE_TESTS}")
message(STATUS "----------------------------------------------------------------------")
```
