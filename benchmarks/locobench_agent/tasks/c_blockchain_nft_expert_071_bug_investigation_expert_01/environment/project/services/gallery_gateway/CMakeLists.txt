cmake_minimum_required(VERSION 3.23)

#
#  HoloCanvas – Gallery Gateway Micro-Service
#  -------------------------------------------------------------
#  This CMake project builds the “gallery_gateway” service, the
#  front-door façade that exposes REST + gRPC endpoints for
#  querying on-chain gallery state, streaming live NFT evolution
#  events, and submitting curator actions.  The service speaks:
#
#    • gRPC (protobuf-based contract shared with other services)
#    • Kafka (event mesh)
#    • TLS (OpenSSL) for secure north-south traffic
#
#  The codebase is pure C17 and uses modern tool-chain hygiene
#  (warnings-as-errors, sanitizers, clang-tidy, coverage, etc.).
#

project(gallery_gateway C)

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------

option(GG_ENABLE_SANITIZERS    "Compile with address/undefined sanitizers"         ON)
option(GG_ENABLE_COVERAGE      "Compile with gcov code-coverage instrumentation"   OFF)
option(GG_ENABLE_CLANG_TIDY    "Run clang-tidy static analysis during the build"   ON)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_EXTENSIONS OFF)

# Treat warnings as errors
if(MSVC)
    add_compile_options(/W4 /WX /permissive-)
else()
    add_compile_options(-Wall -Wextra -Werror -pedantic -Wno-unused-parameter)
endif()

# ---------------------------------------------------------------------------
# Third-party dependencies
# ---------------------------------------------------------------------------

find_package(Threads       REQUIRED)
find_package(OpenSSL       REQUIRED)

# Find Protobuf & gRPC (preferring system install)
find_package(Protobuf 3.21 REQUIRED)
find_package(gRPC      1.50 REQUIRED)

# librdkafka for Kafka connectivity
find_path(RDKAFKA_INCLUDE_DIR rd_kafka.h)
find_library(RDKAFKA_LIBRARY  NAMES rdkafka)

if (NOT RDKAFKA_INCLUDE_DIR OR NOT RDKAFKA_LIBRARY)
    message(FATAL_ERROR "librdkafka not found – install 'librdkafka-dev'")
endif()

# MicroHTTPD for REST fall-back endpoints
find_package(PkgConfig REQUIRED)
pkg_check_modules(MHD microhttpd REQUIRED)

# ---------------------------------------------------------------------------
# Source layout
# ---------------------------------------------------------------------------

set(GG_ROOT_DIR        ${CMAKE_CURRENT_SOURCE_DIR})
set(GG_SRC_DIR         ${GG_ROOT_DIR}/src)
set(GG_INCLUDE_DIR     ${GG_ROOT_DIR}/include)
set(GG_PROTO_DIR       ${GG_ROOT_DIR}/proto)

file(GLOB_RECURSE GG_SOURCE_FILES
     CONFIGURE_DEPENDS
     ${GG_SRC_DIR}/*.c
)

file(GLOB_RECURSE GG_HEADER_FILES
     CONFIGURE_DEPENDS
     ${GG_INCLUDE_DIR}/*.h
)

# ---------------------------------------------------------------------------
# Proto / gRPC code generation
# ---------------------------------------------------------------------------

set(PROTO_FILES
    ${GG_PROTO_DIR}/gallery_api.proto
    ${GG_PROTO_DIR}/events.proto
)

set(GENERATED_SRC_DIR  ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${GENERATED_SRC_DIR})

protobuf_generate(
    LANGUAGE        C
    OUT_VAR         PROTO_SRCS
    IMPORT_DIRS     ${GG_PROTO_DIR}
    PROTOC_OUT_DIR  ${GENERATED_SRC_DIR}
    PROTOS          ${PROTO_FILES}
)

grpc_generate(
    LANGUAGE        C
    OUT_VAR         GRPC_SRCS
    IMPORT_DIRS     ${GG_PROTO_DIR}
    GRPC_PLUGIN     "grpc_c_plugin"
    PROTOC_OUT_DIR  ${GENERATED_SRC_DIR}
    PROTOS          ${PROTO_FILES}
)

# ---------------------------------------------------------------------------
# Build the main executable
# ---------------------------------------------------------------------------

add_executable(gallery_gateway
    ${GG_SOURCE_FILES}
    ${PROTO_SRCS}
    ${GRPC_SRCS}
)

target_include_directories(gallery_gateway
    PRIVATE
        ${GG_INCLUDE_DIR}
        ${GENERATED_SRC_DIR}
        ${Protobuf_INCLUDE_DIRS}
        ${gRPC_INCLUDE_DIRS}
        ${RDKAFKA_INCLUDE_DIR}
        ${MHD_INCLUDE_DIRS}
)

target_link_libraries(gallery_gateway
    PRIVATE
        ${Protobuf_LIBRARIES}
        ${gRPC_LIBRARIES}
        ${RDKAFKA_LIBRARY}
        OpenSSL::SSL
        OpenSSL::Crypto
        ${MHD_LIBRARIES}
        Threads::Threads
)

# ---------------------------------------------------------------------------
# Compiler / linker flags
# ---------------------------------------------------------------------------

if(GG_ENABLE_SANITIZERS AND NOT MSVC)
    target_compile_options(gallery_gateway PRIVATE
        -fsanitize=address,undefined
    )
    target_link_options(gallery_gateway PRIVATE
        -fsanitize=address,undefined
    )
endif()

if(GG_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(gallery_gateway PRIVATE --coverage)
    target_link_libraries(gallery_gateway PRIVATE --coverage)
endif()

# ---------------------------------------------------------------------------
# Clang-tidy
# ---------------------------------------------------------------------------

if(GG_ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if(CLANG_TIDY_EXE)
        set_target_properties(gallery_gateway PROPERTIES
            C_CLANG_TIDY "${CLANG_TIDY_EXE}"
        )
    endif()
endif()

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

enable_testing()

add_subdirectory(test)

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

include(GNUInstallDirs)

install(TARGETS gallery_gateway
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(DIRECTORY ${GG_INCLUDE_DIR}/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/gallery_gateway
        FILES_MATCHING PATTERN "*.h")

# ---------------------------------------------------------------------------
# packaging – CPack
# ---------------------------------------------------------------------------

include(CPack)

set(CPACK_PACKAGE_NAME               "HoloCanvas-gallery_gateway")
set(CPACK_PACKAGE_VERSION            "${PROJECT_VERSION}")
set(CPACK_PACKAGE_CONTACT            "HoloCanvas Core Team <core@holocanvas.io>")
set(CPACK_GENERATOR                  "TGZ;ZIP")
set(CPACK_SOURCE_GENERATOR           "TGZ")
set(CPACK_SOURCE_IGNORE_FILES
    "/build/;/.git/;/.idea/;/*~$;/*.swp$"
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

message(STATUS "-----------------------------------------------------------")
message(STATUS "HoloCanvas :: gallery_gateway")
message(STATUS "  Sources ..............: ${GG_SOURCE_FILES}")
message(STATUS "  Proto sources ........: ${PROTO_SRCS}")
message(STATUS "  gRPC sources .........: ${GRPC_SRCS}")
message(STATUS "  Sanitizers enabled ...: ${GG_ENABLE_SANITIZERS}")
message(STATUS "  Coverage enabled .....: ${GG_ENABLE_COVERAGE}")
message(STATUS "-----------------------------------------------------------")