cmake_minimum_required(VERSION 3.16)

# ================================================================
#  HoloCanvas :: DeFi-Garden Micro-Service
#  ---------------------------------------------------------------
#  This CMake build script produces both a static core library and
#  an executable daemon that implements the on-chain DeFi staking
#  engine.  The service consumes Kafka events, exposes a gRPC API,
#  and signs transactions with OpenSSL-backed crypto primitives.
#
#  Layout:
#      include/              — Public C headers
#      proto/                — Protobuf service definitions
#      src/                  — Implementation (.c)
#      test/                 — Unit/Integration tests (cmocka)
#
#  Third-party deps:
#      • protobuf-c          (message encoding)
#      • gRPC                (service transport)
#      • OpenSSL             (crypto / TLS)
#      • librdkafka          (event bus)
#      • pthread + math      (libc)
#
#  Authoritative source of truth for compile options lives here;
#  DO NOT modify compiler flags in individual sub-directories.
# ================================================================

project(defi_garden VERSION 1.2.0 LANGUAGES C)

# ------------------------------------------------------------------------------
# Global compile configuration
# ------------------------------------------------------------------------------
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Enable extra warnings for production-grade hygiene.
add_compile_options(-Wall -Wextra -Wpedantic -Wstrict-prototypes -Werror)

# ------------------------------------------------------------------------------
# Optional bells & whistles
# ------------------------------------------------------------------------------

option(DEFIGARDEN_ENABLE_ASAN "Enable AddressSanitizer instrumentation" OFF)
if(DEFIGARDEN_ENABLE_ASAN)
    add_compile_options(-fsanitize=address -fno-omit-frame-pointer)
    add_link_options    (-fsanitize=address)
endif()

option(DEFIGARDEN_ENABLE_LTO "Enable Link-Time Optimization (IPO)" ON)
if(DEFIGARDEN_ENABLE_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT ipo_supported OUTPUT ipo_output)
    if(ipo_supported)
        message(STATUS "Inter-Procedural Optimization enabled")
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${ipo_output}")
    endif()
endif()

# ------------------------------------------------------------------------------
# Locate third-party packages
# ------------------------------------------------------------------------------
find_package(OpenSSL      REQUIRED)
find_package(Protobuf     REQUIRED)          # For protoc executable
find_package(PkgConfig    REQUIRED)

# -------- gRPC (C-core) -------------------------------------------------------
# gRPC does not ship a traditional find-module for the C build; search manually.
find_library(GRPC_LIBRARY       grpc        REQUIRED)
find_library(GPR_LIBRARY        gpr         REQUIRED)
find_library(ABSL_LIBRARY       absl_synchronization)  # Optional dependency

# -------- Protobuf-C ----------------------------------------------------------
pkg_check_modules(PROTOBUF_C   REQUIRED libprotobuf-c)
find_path(PROTOBUF_C_INCLUDE_DIR NAMES protobuf-c/protobuf-c.h
           HINTS ${PROTOBUF_C_INCLUDEDIR})
find_library(PROTOBUF_C_LIBRARY NAMES protobuf-c
             HINTS ${PROTOBUF_C_LIBDIR})

# -------- Kafka ---------------------------------------------------------------
pkg_check_modules(RDKAFKA      REQUIRED rdkafka)
find_path(RDKAFKA_INCLUDE_DIR  NAMES rdkafka.h
           HINTS ${RDKAFKA_INCLUDEDIR})
find_library(RDKAFKA_LIBRARY   NAMES rdkafka
             HINTS ${RDKAFKA_LIBDIR})

# ------------------------------------------------------------------------------
# Proto ↦ C Code Generation
# ------------------------------------------------------------------------------
set(PROTO_FILE ${CMAKE_CURRENT_SOURCE_DIR}/proto/defi_garden.proto)
set(GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${GENERATED_DIR})

add_custom_command(
    OUTPUT  ${GENERATED_DIR}/defi_garden.pb-c.c
            ${GENERATED_DIR}/defi_garden.pb-c.h
    COMMAND protoc
            --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto
            --c_out=${GENERATED_DIR}
            ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    COMMENT "Generating protobuf-c sources for DeFi-Garden"
    VERBATIM
)

# ------------------------------------------------------------------------------
# Core Library
# ------------------------------------------------------------------------------
set(SERVICE_SOURCES
    src/defi_garden.c
    src/defi_pool.c
    src/defi_stake.c
    src/defi_strategy.c
    src/events/kafka_dispatcher.c
    src/events/grpc_server.c
    src/utils/log.c
    src/utils/config.c
    ${GENERATED_DIR}/defi_garden.pb-c.c
)

add_library(defi_garden_core STATIC ${SERVICE_SOURCES})

target_include_directories(defi_garden_core
    PUBLIC
        include
        ${GENERATED_DIR}
        ${RDKAFKA_INCLUDE_DIR}
        ${PROTOBUF_C_INCLUDE_DIR}
        ${OPENSSL_INCLUDE_DIR}
)

target_link_libraries(defi_garden_core
    PUBLIC
        ${OPENSSL_LIBRARIES}
        ${RDKAFKA_LIBRARY}
        ${GRPC_LIBRARY}
        ${GPR_LIBRARY}
        ${ABSL_LIBRARY}
        ${PROTOBUF_C_LIBRARY}
        pthread
        m
)

# ------------------------------------------------------------------------------
# Service Daemon Executable
# ------------------------------------------------------------------------------
add_executable(defi_garden_service src/main.c)
target_link_libraries(defi_garden_service PRIVATE defi_garden_core)

# ------------------------------------------------------------------------------
# Version Header (generated at configure time)
# ------------------------------------------------------------------------------
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/include/defi_garden/version.h.in
    ${GENERATED_DIR}/version.h
    @ONLY
)
target_include_directories(defi_garden_core PUBLIC ${GENERATED_DIR})

# ------------------------------------------------------------------------------
# Installation
# ------------------------------------------------------------------------------
include(GNUInstallDirs)
install(TARGETS defi_garden_service
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(TARGETS defi_garden_core
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/defi_garden
        FILES_MATCHING PATTERN "*.h")

install(DIRECTORY ${GENERATED_DIR}/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/defi_garden
        FILES_MATCHING PATTERN "*.h")

install(FILES ${PROTO_FILE}
        DESTINATION share/defi_garden/proto)

# ------------------------------------------------------------------------------
# Testing (cmocka)
# ------------------------------------------------------------------------------
enable_testing()
pkg_check_modules(CMOCKA cmocka)
if(CMOCKA_FOUND)
    add_subdirectory(test)
else()
    message(STATUS "cmocka not found — unit tests will be skipped.")
endif()

# End of CMakeLists.txt
