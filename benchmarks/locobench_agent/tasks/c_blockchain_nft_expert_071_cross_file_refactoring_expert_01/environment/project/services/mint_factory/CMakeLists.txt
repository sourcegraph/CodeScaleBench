cmake_minimum_required(VERSION 3.20)

# ──────────────────────────────────────────────────────────────────────────────
#  HoloCanvas :: Mint-Factory
#  ------------------------------------------------
#  A micro-service responsible for compositing shader, audio and metadata
#  fragments into an immutable on-chain NFT recipe.
# ──────────────────────────────────────────────────────────────────────────────
#  This CMakeLists.txt configures:
#    • Core static/shared library (mint_factory_core)
#    • Stand-alone service binary  (mint_factory_service)
#    • Protocol-buffer (protobuf-c) code-gen step
#    • Optional sanitizers, coverage and unit tests
# ──────────────────────────────────────────────────────────────────────────────

project(mint_factory LANGUAGES C VERSION 1.0.0)

# ──────────────────────────────────────────────────────────────────────────────
#  Global build settings
# ──────────────────────────────────────────────────────────────────────────────
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(ENABLE_SANITIZER        "Enable Address + UB sanitizers" OFF)
option(ENABLE_COVERAGE         "Compile with coverage instrumentation" OFF)
option(BUILD_SHARED_LIBS       "Build shared instead of static libs" ON)
option(BUILD_TESTING           "Build unit/integration tests" ON)

# ──────────────────────────────────────────────────────────────────────────────
#  Warning / diagnostics flags
# ──────────────────────────────────────────────────────────────────────────────
if (MSVC)
    add_compile_options(/W4 /WX)
else()
    add_compile_options(
        -Wall -Wextra -Wpedantic -Wshadow
        -Wstrict-prototypes -Wformat=2
        -Werror
    )
endif()

# ──────────────────────────────────────────────────────────────────────────────
#  Sanitizers & Coverage
# ──────────────────────────────────────────────────────────────────────────────
if (ENABLE_SANITIZER AND NOT MSVC)
    message(STATUS "Building with sanitizers enabled")
    add_compile_options(-fsanitize=address,undefined)
    add_link_options   (-fsanitize=address,undefined)
endif()

if (ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    message(STATUS "Building with code-coverage instrumentation")
    add_compile_options(--coverage -O0)
    add_link_options(--coverage)
endif()

# ──────────────────────────────────────────────────────────────────────────────
#  Dependencies
# ──────────────────────────────────────────────────────────────────────────────
find_package(Threads   REQUIRED)
find_package(PkgConfig REQUIRED)

pkg_check_modules(PROTOBUF_C   REQUIRED IMPORTED_TARGET protobuf-c)
pkg_check_modules(GRPC         REQUIRED IMPORTED_TARGET grpc)      # C-core
pkg_check_modules(OPENSSL      REQUIRED IMPORTED_TARGET openssl)
pkg_check_modules(LIBRDKAFKA   REQUIRED IMPORTED_TARGET rdkafka)
pkg_check_modules(ZLIB         REQUIRED IMPORTED_TARGET zlib)

# ──────────────────────────────────────────────────────────────────────────────
#  Protocol Buffer (protobuf-c) code generation
# ──────────────────────────────────────────────────────────────────────────────
set(PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/proto)
file(GLOB PROTO_FILES CONFIGURE_DEPENDS "${PROTO_DIR}/*.proto")

if (NOT PROTO_FILES)
    message(FATAL_ERROR "No .proto files found in ${PROTO_DIR}")
endif()

foreach(proto ${PROTO_FILES})
    get_filename_component(proto_name ${proto} NAME_WE)
    set(proto_src "${CMAKE_CURRENT_BINARY_DIR}/${proto_name}.pb-c.c")
    set(proto_hdr "${CMAKE_CURRENT_BINARY_DIR}/${proto_name}.pb-c.h")

    add_custom_command(
        OUTPUT  ${proto_src} ${proto_hdr}
        COMMAND protoc
                --proto_path=${PROTO_DIR}
                --c_out=${CMAKE_CURRENT_BINARY_DIR}
                ${proto}
        DEPENDS ${proto}
        COMMENT "Generating C source from ${proto}"
        VERBATIM
    )

    list(APPEND GENERATED_SRCS ${proto_src})
    list(APPEND GENERATED_HDRS ${proto_hdr})
endforeach()

# ──────────────────────────────────────────────────────────────────────────────
#  Mint-Factory library
# ──────────────────────────────────────────────────────────────────────────────
file(GLOB_RECURSE SOURCE_SRCS CONFIGURE_DEPENDS "src/*.c")
add_library(mint_factory_core
    ${SOURCE_SRCS}
    ${GENERATED_SRCS}
    ${GENERATED_HDRS}
)

target_include_directories(mint_factory_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(mint_factory_core
    PUBLIC
        PkgConfig::PROTOBUF_C
        PkgConfig::GRPC
        PkgConfig::OPENSSL
        PkgConfig::LIBRDKAFKA
        PkgConfig::ZLIB
        Threads::Threads
)

set_target_properties(mint_factory_core
    PROPERTIES
        VERSION   ${PROJECT_VERSION}
        SOVERSION 1
)

add_library(HoloCanvas::mint_factory ALIAS mint_factory_core)

# ──────────────────────────────────────────────────────────────────────────────
#  Service executable
# ──────────────────────────────────────────────────────────────────────────────
add_executable(mint_factory_service src/main.c)
target_link_libraries(mint_factory_service PRIVATE mint_factory_core)

# ──────────────────────────────────────────────────────────────────────────────
#  Installation
# ──────────────────────────────────────────────────────────────────────────────
include(GNUInstallDirs)

install(TARGETS mint_factory_core
        EXPORT  mint_factoryTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(TARGETS mint_factory_service
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

install(EXPORT mint_factoryTargets
        NAMESPACE HoloCanvas::
        FILE mint_factoryTargets.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/mint_factory)

# ──────────────────────────────────────────────────────────────────────────────
#  Testing
# ──────────────────────────────────────────────────────────────────────────────
if (BUILD_TESTING)
    enable_testing()
    # Assumes CMocka is available through pkg-config
    pkg_check_modules(CMOCKA REQUIRED IMPORTED_TARGET cmocka)
    file(GLOB TEST_SRCS CONFIGURE_DEPENDS "tests/*.c")

    add_executable(mint_factory_tests ${TEST_SRCS})
    target_link_libraries(mint_factory_tests
        PRIVATE
            mint_factory_core
            PkgConfig::CMOCKA
    )

    add_test(
        NAME    mint_factory_unit
        COMMAND mint_factory_tests
    )
endif()

# ──────────────────────────────────────────────────────────────────────────────
#  Formatting helper (clang-format)
# ──────────────────────────────────────────────────────────────────────────────
find_program(CLANG_FORMAT_EXE NAMES clang-format)
if (CLANG_FORMAT_EXE)
    file(GLOB_RECURSE ALL_C_SOURCES
        CONFIGURE_DEPENDS
        ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c
        ${CMAKE_CURRENT_SOURCE_DIR}/include/*.h
        ${PROTO_FILES}
    )
    add_custom_target(format
        COMMAND ${CLANG_FORMAT_EXE} -i ${ALL_C_SOURCES}
        COMMENT "Running clang-format on source files"
    )
endif()
