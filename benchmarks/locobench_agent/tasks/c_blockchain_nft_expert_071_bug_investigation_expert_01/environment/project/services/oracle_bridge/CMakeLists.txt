```cmake
#
#  HoloCanvas – Oracle-Bridge Service
#
#  CMake build script (production-grade)
#  -------------------------------------
#  This component streams external market / weather data into the chain
#  through Kafka topics, verifies payloads with OpenSSL, and exposes a
#  gRPC interface consumed by on-chain “Muse” contracts.
#

cmake_minimum_required (VERSION 3.20 FATAL_ERROR)

# --------------------------------------------------------------------------
# Project meta
# --------------------------------------------------------------------------
project (
    oracle_bridge
    VERSION 1.4.2                                   # Semantic versioning
    DESCRIPTION "Oracle Bridge micro-service for HoloCanvas"
    LANGUAGES C                                     # Pure-C implementation
)

# --------------------------------------------------------------------------
# Build options
# --------------------------------------------------------------------------
option (ORACLE_BRIDGE_BUILD_TESTS     "Build unit / integration tests"       ON)
option (ORACLE_BRIDGE_ENABLE_SANITIZE "Enable Clang/ GCC sanitizers"         OFF)
option (ORACLE_BRIDGE_WARNINGS_AS_ERR "Treat warnings as errors"             ON)
option (ORACLE_BRIDGE_STATIC_LINK     "Link all third-party deps statically" OFF)

# --------------------------------------------------------------------------
# Output directories
# --------------------------------------------------------------------------
set (CMAKE_ARCHIVE_OUTPUT_DIRECTORY   ${CMAKE_BINARY_DIR}/lib)
set (CMAKE_LIBRARY_OUTPUT_DIRECTORY   ${CMAKE_BINARY_DIR}/lib)
set (CMAKE_RUNTIME_OUTPUT_DIRECTORY   ${CMAKE_BINARY_DIR}/bin)

# --------------------------------------------------------------------------
# Global compiler flags
# --------------------------------------------------------------------------
include (CheckCCompilerFlag)
function (add_if_supported flag var)
    check_c_compiler_flag ("${flag}" "${var}")
    if (${${var}})
        add_compile_options ("${flag}")
    endif ()
endfunction ()

add_if_supported ("-Wall"             HAS_WALL)
add_if_supported ("-Wextra"           HAS_WEXTRA)
add_if_supported ("-Wshadow"          HAS_WSHADOW)
add_if_supported ("-Wpedantic"        HAS_WPEDANTIC)
add_if_supported ("-Wformat=2"        HAS_WFORMAT2)
add_if_supported ("-Wstrict-prototypes" HAS_STRICT_PROTO)

if (ORACLE_BRIDGE_WARNINGS_AS_ERR)
    add_if_supported ("-Werror" HAS_WERROR)
endif ()

if (CMAKE_BUILD_TYPE MATCHES "Debug")
    add_compile_definitions (DEBUG)
    add_if_supported ("-Og" HAS_OG)
else ()
    add_if_supported ("-O3" HAS_O3)
endif ()

# --------------------------------------------------------------------------
# Sanitizers (optional)
# --------------------------------------------------------------------------
if (ORACLE_BRIDGE_ENABLE_SANITIZE AND (CMAKE_C_COMPILER_ID MATCHES "Clang|GNU"))
    message (STATUS "Enabling sanitizers")
    add_compile_options (-fsanitize=address -fno-omit-frame-pointer)
    add_link_options    (-fsanitize=address)
endif ()

# --------------------------------------------------------------------------
# Dependency discovery
# --------------------------------------------------------------------------
include (FindPkgConfig)

# --- OpenSSL ---------------------------------------------------------------
find_package (OpenSSL 1.1 REQUIRED)

# --- Kafka (librdkafka) ----------------------------------------------------
pkg_check_modules (RDKAFKA REQUIRED IMPORTED_TARGET librdkafka>=1.9)

# --- Protobuf & gRPC -------------------------------------------------------
find_package (Protobuf 3.15 REQUIRED)
find_package (gRPC CONFIG REQUIRED)
if (ORACLE_BRIDGE_STATIC_LINK)
    # Force static linking for third-party libs (if available)
    set (gRPC_USE_STATIC_LIBS ON CACHE BOOL "" FORCE)
endif ()

# --------------------------------------------------------------------------
# Proto compilation (gRPC / Protobuf codegen)
# --------------------------------------------------------------------------
set (ORACLE_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/proto)
set (ORACLE_GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)

file (GLOB ORACLE_PROTO_FILES CONFIGURE_DEPENDS
      "${ORACLE_PROTO_DIR}/*.proto")

# Generate C stubs using the gRPC C plugin
set_property (DIRECTORY PROPERTY
    PROTOBUF_GENERATE_CPP_APPEND_PATH OFF) # Keep output flat

protobuf_generate (
    LANGUAGE          C
    OUT_VAR           PROTO_SRCS
    PROTOC_OUT_DIR    ${ORACLE_GENERATED_DIR}
    PROTO_FILES       ${ORACLE_PROTO_FILES}
)

# --------------------------------------------------------------------------
# Source files
# --------------------------------------------------------------------------
set (ORACLE_BRIDGE_SRC
    src/bridge_main.c
    src/kafka_ingress.c
    src/kafka_ingress.h
    src/grpc_server.c
    src/grpc_server.h
    src/crypto_utils.c
    src/crypto_utils.h
    ${PROTO_SRCS}
)

# --------------------------------------------------------------------------
# Library target (static, used by unit tests)
# --------------------------------------------------------------------------
add_library (oracle_bridge_core STATIC
    ${ORACLE_BRIDGE_SRC}
)

target_include_directories (oracle_bridge_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${ORACLE_GENERATED_DIR}>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries (oracle_bridge_core
    PUBLIC
        OpenSSL::SSL
        OpenSSL::Crypto
        PkgConfig::RDKAFKA
        gRPC::grpc
        protobuf::libprotobuf
)

set_target_properties (oracle_bridge_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    OUTPUT_NAME                "oracle_bridge_core"
)

# --------------------------------------------------------------------------
# Executable target
# --------------------------------------------------------------------------
add_executable (oracle_bridge
    src/service_entrypoint.c
)
target_link_libraries (oracle_bridge
    PRIVATE oracle_bridge_core
)

# Provide RPATH for installed targets on UNIX
if (UNIX AND NOT APPLE)
    set_target_properties (oracle_bridge PROPERTIES
        INSTALL_RPATH "$ORIGIN/../lib"
    )
endif ()

# --------------------------------------------------------------------------
# Unit & integration tests
# --------------------------------------------------------------------------
if (ORACLE_BRIDGE_BUILD_TESTS)
    enable_testing ()
    add_subdirectory (tests)
endif ()

# --------------------------------------------------------------------------
# Installation rules
# --------------------------------------------------------------------------
include (GNUInstallDirs)

install (TARGETS oracle_bridge oracle_bridge_core
    EXPORT oracle_bridge_targets
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install (DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install (DIRECTORY ${ORACLE_GENERATED_DIR}/
         DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/oracle_bridge/proto)

# Export the target list for downstream projects
install (EXPORT oracle_bridge_targets
    FILE oracle_bridgeConfig.cmake
    NAMESPACE HoloCanvas::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/oracle_bridge
)

# --------------------------------------------------------------------------
# Packaging (CPack)
# --------------------------------------------------------------------------
include (CPack)

set (CPACK_PACKAGE_NAME               "oracle_bridge")
set (CPACK_PACKAGE_VENDOR             "HoloCanvas")
set (CPACK_PACKAGE_VERSION            ${PROJECT_VERSION})
set (CPACK_PACKAGE_CONTACT            "dev@holocanvas.io")
set (CPACK_PACKAGE_DESCRIPTION_SUMMARY
    "HoloCanvas Oracle-Bridge – secure Kafka / gRPC feed into the chain")

if (WIN32)
    set (CPACK_GENERATOR "ZIP")
else ()
    set (CPACK_GENERATOR "TGZ")
endif ()

# --------------------------------------------------------------------------
# Developer helper targets
# --------------------------------------------------------------------------
# Format code with clang-format (run: make fmt)
find_program (CLANG_FORMAT NAMES clang-format)
if (CLANG_FORMAT)
    file (GLOB_RECURSE ALL_C_SOURCES
        src/*.c src/*.h include/*.h)

    add_custom_target (fmt
        COMMAND ${CLANG_FORMAT}
        -i
        -style=file
        ${ALL_C_SOURCES}
        COMMENT "Formatting source files"
    )
endif ()
```