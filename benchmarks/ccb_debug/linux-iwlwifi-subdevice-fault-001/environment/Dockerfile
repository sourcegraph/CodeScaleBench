# Pre-built base image contains gcc:13, tools, Claude Code CLI, and the
# Linux kernel source at v5.6-rc2.  Build it first if missing:
#   ./benchmarks/ccb_linuxflbench/base_images/build_base_images.sh v5.6-rc2
# See benchmarks/ccb_linuxflbench/README.md for details.
FROM ccb-linux-base:v5.6-rc2

# Tests are uploaded at runtime by Harbor verifier to /tests/
# No additional build steps needed — base image has everything.
