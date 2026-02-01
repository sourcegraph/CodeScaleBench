cmake_minimum_required(VERSION 3.20)

# ==============================================================================
#  HoloCanvas : Ledger-Core Service
#  ---------------------------------
#  This CMake configuration drives the build for the Ledger-Core micro-service.
#  Ledger-Core is written in modern ISO C and links against a collection of
#  third-party libraries (Kafka, gRPC, OpenSSL, libsodium, etc.) to provide
#  deterministic, high-throughput transaction handling for the HoloCanvas
#  platform.
# ==============================================================================

project(ledger_core
        VERSION 0.4.0
        DESCRIPTION "Ledger-Core service for the HoloCanvas micro-gallery blockchain"
        LANGUAGES C)

# --------------------------------------------------------------------------
# Build-type presets
# --------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING
        "Choose the type of build (Debug, Release, RelWithDebInfo, MinSizeRel)"
        FORCE)
endif()

# --------------------------------------------------------------------------
# Compiler requirements & flags
# --------------------------------------------------------------------------
set(CMAKE_C_STANDARD 18)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(
        -Wall -Wextra -Wpedantic
        -Wshadow -Wformat=2 -Wconversion
        -Wno-missing-field-initializers
    )
elseif(MSVC)
    add_compile_options(/W4 /permissive- /external:W0 /WX)
endif()

# --------------------------------------------------------------------------
# User-configurable feature toggles
# --------------------------------------------------------------------------
option(LEDGER_CORE_ENABLE_ASAN         "Build with AddressSanitizer"            OFF)
option(LEDGER_CORE_ENABLE_UBSAN        "Build with UndefinedBehaviorSanitizer"  OFF)
option(LEDGER_CORE_ENABLE_COVERAGE     "Enable code-coverage instrumentation"   OFF)
option(LEDGER_CORE_BUILD_TESTS         "Build unit / integration tests"         ON)
option(LEDGER_CORE_ENABLE_LTO          "Enable link-time optimisation (IPO)"    ON)

# --------------------------------------------------------------------------
# Sanitizer / coverage instrumentation
# --------------------------------------------------------------------------
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    if(LEDGER_CORE_ENABLE_ASAN)
        add_compile_options(-fsanitize=address -fno-omit-frame-pointer)
        add_link_options    (-fsanitize=address -fno-omit-frame-pointer)
    endif()

    if(LEDGER_CORE_ENABLE_UBSAN)
        add_compile_options(-fsanitize=undefined -fno-omit-frame-pointer)
        add_link_options    (-fsanitize=undefined -fno-omit-frame-pointer)
    endif()

    if(LEDGER_CORE_ENABLE_COVERAGE)
        add_compile_options(--coverage -O0)
        add_link_options    (--coverage)
    endif()
endif()

# --------------------------------------------------------------------------
# Try to enable link-time optimisation
# --------------------------------------------------------------------------
include(CheckIPOSupported)
if(LEDGER_CORE_ENABLE_LTO)
    check_ipo_supported(RESULT IPO_SUPPORTED OUTPUT IPO_ERROR)
    if(IPO_SUPPORTED)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${IPO_ERROR}")
    endif()
endif()

# --------------------------------------------------------------------------
# External dependencies
# --------------------------------------------------------------------------
include(GNUInstallDirs)
include(FetchContent)
include(CMakePrintHelpers)
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(Sodium 1.0 REQUIRED)   # libsodium
find_package(Protobuf REQUIRED)

# librdkafka via pkg-config
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBRDKAFKA REQUIRED librdkafka)

# gRPC-C via pkg-config (the HoloCanvas build system ships gRPC-C wrappers)
pkg_check_modules(GRPC REQUIRED grpc)

# Lightweight JSON library (cJSON) via FetchContent as fallback
FetchContent_Declare(
    cJSON
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG        v1.7.15           # Keep in sync with security notices
)
FetchContent_MakeAvailable(cJSON)    # Provides target cjson

# --------------------------------------------------------------------------
# Source layout
# --------------------------------------------------------------------------
set(LEDGER_CORE_PUBLIC_HEADERS
    include/ledger/block.h
    include/ledger/transaction.h
    include/ledger/wallet.h
    include/ledger/consensus.h
    include/ledger/serialization.h
    include/ledger/event_bus.h
    include/ledger/crypto.h
    include/ledger/kafka_adapter.h
    include/ledger/grpc_adapter.h
    include/ledger/ledger.h
)

set(LEDGER_CORE_PRIVATE_SOURCES
    src/block.c
    src/transaction.c
    src/wallet.c
    src/consensus.c
    src/serialization.c
    src/event_bus.c
    src/kafka_adapter.c
    src/grpc_adapter.c
    src/crypto.c
    src/ledger.c
)

add_library(ledger_core STATIC
    ${LEDGER_CORE_PUBLIC_HEADERS}
    ${LEDGER_CORE_PRIVATE_SOURCES}
)

# --------------------------------------------------------------------------
# Include directories & compile definitions
# --------------------------------------------------------------------------
target_include_directories(ledger_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    PRIVATE
        ${LIBRDKAFKA_INCLUDE_DIRS}
        ${GRPC_INCLUDE_DIRS}
        ${Protobuf_INCLUDE_DIRS}
)

target_compile_definitions(ledger_core
    PUBLIC
        LEDGER_CORE_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
        LEDGER_CORE_VERSION_MINOR=${PROJECT_VERSION_MINOR}
        LEDGER_CORE_VERSION_PATCH=${PROJECT_VERSION_PATCH}
)

# --------------------------------------------------------------------------
# Linkage
# --------------------------------------------------------------------------
target_link_libraries(ledger_core
    PUBLIC
        Threads::Threads
        OpenSSL::SSL
        OpenSSL::Crypto
        Sodium::Sodium
        cjson
        ${LIBRDKAFKA_LIBRARIES}
        ${GRPC_LIBRARIES}
        ${Protobuf_LIBRARIES}
)

# --------------------------------------------------------------------------
# Installation rules
# --------------------------------------------------------------------------
install(
    TARGETS ledger_core
    EXPORT  ledger_coreTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

# Export target for downstream find_package
install(
    EXPORT ledger_coreTargets
    FILE   ledger_coreTargets.cmake
    NAMESPACE holo::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/ledger_core
)

# --------------------------------------------------------------------------
# Pkg-config (.pc) file for C dev environment
# --------------------------------------------------------------------------
configure_file(
    cmake/ledger_core.pc.in
    ${CMAKE_CURRENT_BINARY_DIR}/ledger_core.pc
    @ONLY
)
install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/ledger_core.pc
    DESTINATION ${CMAKE_INSTALL_DATAROOTDIR}/pkgconfig
)

# --------------------------------------------------------------------------
# Documentation target (Doxygen)
# --------------------------------------------------------------------------
find_package(Doxygen QUIET)
if(DOXYGEN_FOUND)
    set(DOXYGEN_IN  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/Doxyfile.in)
    set(DOXYGEN_OUT ${CMAKE_CURRENT_BINARY_DIR}/Doxyfile)

    configure_file(${DOXYGEN_IN} ${DOXYGEN_OUT} @ONLY)

    add_custom_target(doc
        COMMAND ${DOXYGEN_EXECUTABLE} ${DOXYGEN_OUT}
        WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
        COMMENT "Generating Ledger-Core API documentation with Doxygen"
        VERBATIM
    )
endif()

# --------------------------------------------------------------------------
# clang-format helper target
# --------------------------------------------------------------------------
find_program(CLANG_FORMAT_BIN clang-format)
if(CLANG_FORMAT_BIN)
    add_custom_target(format
        COMMAND ${CLANG_FORMAT_BIN}
                -i
                $<JOIN:${LEDGER_CORE_PUBLIC_HEADERS}, >
                $<JOIN:${LEDGER_CORE_PRIVATE_SOURCES}, >
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "Automatically formatting Ledger-Core C sources"
    )
endif()

# --------------------------------------------------------------------------
# Unit / Integration tests
# --------------------------------------------------------------------------
if(LEDGER_CORE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(test)
endif()

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
cmake_print_variables(
    CMAKE_BUILD_TYPE
    LEDGER_CORE_ENABLE_ASAN
    LEDGER_CORE_ENABLE_UBSAN
    LEDGER_CORE_ENABLE_COVERAGE
    LEDGER_CORE_ENABLE_LTO
)