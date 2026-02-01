#!/usr/bin/env python3
"""Test for hello_world.py"""

import subprocess
import sys
from pathlib import Path

def test_hello_world():
    """Test that hello_world.py exists and outputs correctly."""

    # Check file exists
    hello_file = Path("/workspace/hello_world.py")
    if not hello_file.exists():
        print(f"FAIL: File not found: {hello_file}")
        sys.exit(1)

    # Run the script
    try:
        result = subprocess.run(
            ["python", str(hello_file)],
            capture_output=True,
            text=True,
            timeout=5
        )
    except subprocess.TimeoutExpired:
        print("FAIL: Script timed out")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: Error running script: {e}")
        sys.exit(1)

    # Check output
    expected = "Hello, World!\n"
    if result.stdout == expected:
        print("PASS: hello_world.py outputs correctly")
        sys.exit(0)
    else:
        print(f"FAIL: Expected output: {repr(expected)}")
        print(f"FAIL: Actual output: {repr(result.stdout)}")
        sys.exit(1)

if __name__ == "__main__":
    test_hello_world()
