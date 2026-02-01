# ----------------------------------------------------------------------------------------------------------------------
# HoloCanvas :: Governance-Hall Micro-Service
#
# CMake build recipe for the Governance-Hall component.  This micro-service coordinates DAO-style on-chain governance
# around evolving NFT artifacts.  It links against the shared “canvas_core” lib for cryptographic utilities as well as
# third-party libraries for gRPC, protobuf-c, Kafka, and OpenSSL.  Unit-tests are driven via CMocka, and packaging is
# handled through CPack.
#
# Target layout
#   /src              → C source files
#   /include          → Public headers for other services
#   /proto            → gRPC / protobuf contracts (compiled to C using protobuf-c + gRPC-c)
#   /tests            → Unit/integration tests
#
# ----------------------------------------------------------------------------------------------------------------------

cmake_minimum_required(VERSION 3.20)
project(holo_governance_hall C CXX)   # Build in C11 but allow C++ for third-party headers

# ----------------------------------------------------------------------------------------------------------------------
# Build Options
# ----------------------------------------------------------------------------------------------------------------------

option(ENABLE_LTO           "Enable Link-Time-Optimization"            ON)
option(ENABLE_CLANG_TIDY    "Run clang-tidy static analysis"           OFF)
option(ENABLE_TESTING       "Build unit / integration tests"           ON)
option(ENABLE_COVERAGE      "Enable coverage flags (GCC/Clang only)"   OFF)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Warn aggressively.
if(NOT MSVC)
    add_compile_options(-Wall -Wextra -Werror -Wshadow -Wpedantic -Wmissing-prototypes
                        -Wformat=2 -Wno-unused-parameter)
else()
    add_compile_options(/W4 /WX)
endif()

# Coverage flags.
if(ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(--coverage -O0)
    list(APPEND EXTRA_LINK_FLAGS --coverage)
endif()

# LTO flags.
include(CheckIPOSupported)
if(ENABLE_LTO)
    check_ipo_supported(RESULT IPO_SUPPORTED OUTPUT IPO_ERROR)
    if(IPO_SUPPORTED)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${IPO_ERROR}")
    endif()
endif()

# clang-tidy
if(ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if(CLANG_TIDY_EXE)
        set(CMAKE_C_CLANG_TIDY ${CLANG_TIDY_EXE})
    else()
        message(WARNING "clang-tidy not found; disabling static analysis.")
    endif()
endif()

# ----------------------------------------------------------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------------------------------------------------------

include(FetchContent)

# ---- Protobuf-C ----
find_package(ProtobufC REQUIRED)
# ---- gRPC-C (assumes system install, e.g., via vcpkg or distro) ----
find_library(GRPC_C grpc_c REQUIRED)
# ---- Kafka (librdkafka) ----
find_package(PkgConfig REQUIRED)
pkg_check_modules(RDKAFKA REQUIRED IMPORTED_TARGET librdkafka)
# ---- OpenSSL ----
find_package(OpenSSL REQUIRED)

# ---- Canvas Core (shared internal library) ----
# Expect installed to the build tree’s parent or fetched via FetchContent.
FetchContent_Declare(
    canvas_core
    GIT_REPOSITORY  https://github.com/holocanvas/canvas_core.git
    GIT_TAG         v1.4.2
)
FetchContent_MakeAvailable(canvas_core)

# ----------------------------------------------------------------------------------------------------------------------
# Proto / gRPC code generation
# ----------------------------------------------------------------------------------------------------------------------

file(GLOB PROTO_FILES "${CMAKE_CURRENT_SOURCE_DIR}/proto/*.proto")

# Generate C bindings using protobuf-c.
set(PROTO_C_OUT "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${PROTO_C_OUT}")

foreach(proto ${PROTO_FILES})
    get_filename_component(proto_name ${proto} NAME_WE)
    add_custom_command(
        OUTPUT  "${PROTO_C_OUT}/${proto_name}.pb-c.c"
                "${PROTO_C_OUT}/${proto_name}.pb-c.h"
        COMMAND protoc
                --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto
                --c_out=${PROTO_C_OUT}
                --grpc_out=${PROTO_C_OUT}
                --plugin=protoc-gen-grpc=$(which grpc_c_plugin)
                ${proto}
        DEPENDS ${proto}
        COMMENT "Generating C sources from ${proto}"
        VERBATIM
    )
    list(APPEND GENERATED_PROTO_SRCS "${PROTO_C_OUT}/${proto_name}.pb-c.c")
    list(APPEND GENERATED_PROTO_HDRS "${PROTO_C_OUT}/${proto_name}.pb-c.h")
endforeach()

# ----------------------------------------------------------------------------------------------------------------------
# Library Target: governance_hall
# ----------------------------------------------------------------------------------------------------------------------

file(GLOB_RECURSE GOV_HALL_SRCS
     CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c"
     "${GENERATED_PROTO_SRCS}"
)

add_library(governance_hall STATIC
    ${GOV_HALL_SRCS}
    ${GENERATED_PROTO_HDRS}
)

target_include_directories(governance_hall
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${PROTO_C_OUT}
)

target_link_libraries(governance_hall
    PRIVATE
        canvas_core
        ProtobufC::ProtobufC
        ${GRPC_C}
        PkgConfig::RDKAFKA
        OpenSSL::SSL
        OpenSSL::Crypto
        ${EXTRA_LINK_FLAGS}
)

set_target_properties(governance_hall PROPERTIES
    VERSION   1.2.0
    SOVERSION 1
)

# ----------------------------------------------------------------------------------------------------------------------
# Executable: governance_halld (daemon)
# ----------------------------------------------------------------------------------------------------------------------

add_executable(governance_halld src/main.c)
target_link_libraries(governance_halld PRIVATE governance_hall)

install(TARGETS governance_hall governance_halld
        EXPORT governance_hallTargets
        RUNTIME DESTINATION bin
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
)

install(DIRECTORY include/ DESTINATION include)

# ----------------------------------------------------------------------------------------------------------------------
# Unit/Integration Tests
# ----------------------------------------------------------------------------------------------------------------------
if(ENABLE_TESTING)
    enable_testing()
    # --- CMocka (pulled via FetchContent if missing) ---
    FetchContent_Declare(
        cmocka
        GIT_REPOSITORY https://git.cryptomilk.org/projects/cmocka.git
        GIT_TAG        cmocka-1.1.7
    )
    FetchContent_MakeAvailable(cmocka)

    file(GLOB_RECURSE TEST_SRCS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tests/*.c")

    add_executable(governance_hall_tests ${TEST_SRCS})
    target_link_libraries(governance_hall_tests
        PRIVATE governance_hall cmocka::cmocka
    )
    add_test(NAME governance_hall ALL COMMAND governance_hall_tests)
endif()

# ----------------------------------------------------------------------------------------------------------------------
# Packaging
# ----------------------------------------------------------------------------------------------------------------------
include(CPack)
set(CPACK_PACKAGE_NAME           "HoloCanvas-GovernanceHall")
set(CPACK_PACKAGE_VENDOR         "HoloCanvas Collective")
set(CPACK_PACKAGE_VERSION        "1.2.0")
set(CPACK_PACKAGE_CONTACT        "dev@holocanvas.io")
set(CPACK_DEBIAN_PACKAGE_SECTION "utils")
set(CPACK_RPM_PACKAGE_GROUP      "Applications/Blockchain")
set(CPACK_GENERATOR              "TGZ;DEB;RPM")
cpack()

# ----------------------------------------------------------------------------------------------------------------------
# Developer Information
# ----------------------------------------------------------------------------------------------------------------------
message(STATUS "Governance-Hall build configuration complete:")
message(STATUS "  LTO                 : ${ENABLE_LTO}")
message(STATUS "  clang-tidy          : ${ENABLE_CLANG_TIDY}")
message(STATUS "  Coverage            : ${ENABLE_COVERAGE}")
message(STATUS "  Tests               : ${ENABLE_TESTING}")
