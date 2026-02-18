# Pre-built base image contains gcc:13, tools, Claude Code CLI, and the
# Linux kernel source at v4.1.15.  Build it first if missing:
#   ./benchmarks/ccb_linuxflbench/base_images/build_base_images.sh v4.1.15
# See benchmarks/ccb_linuxflbench/README.md for details.
FROM ccb-linux-base:v4.1.15

# Tests are uploaded at runtime by Harbor verifier to /tests/
# No additional build steps needed — base image has everything.
