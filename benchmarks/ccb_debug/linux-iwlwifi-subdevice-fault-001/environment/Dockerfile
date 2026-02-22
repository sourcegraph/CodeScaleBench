# Pre-built base image contains gcc:13, python3, tools, and the
# Linux kernel source at v5.6-rc2.  Build it first if missing:
#   ./scripts/build_linux_base_images.sh v5.6-rc2
FROM ccb-linux-base:v5.6-rc2

# Tests are uploaded at runtime by Harbor verifier to /tests/
# No additional build steps needed — base image has everything.
