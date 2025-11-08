"""Test script for secure_shell module."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.secure_shell import execute_shell, ShellResponse

def test_basic_command():
    """Test basic command execution."""
    print("Testing basic command...")
    result = execute_shell("echo 'Hello World'")
    print(f"Command: {result.command}")
    print(f"Stdout: {result.stdout.strip()}")
    print(f"Success: {result.success}")
    print(f"Execution time: {result.execution_time:.4f}s")
    assert result.success
    assert "Hello World" in result.stdout
    print("✓ Basic command test passed\n")

def test_markdown_wrapped():
    """Test command with markdown code fences."""
    print("Testing markdown-wrapped command...")
    markdown_cmd = """```bash
echo 'Test with markdown'
```"""
    result = execute_shell(markdown_cmd)
    print(f"Original: {repr(markdown_cmd)}")
    print(f"Cleaned command: {result.command}")
    print(f"Stdout: {result.stdout.strip()}")
    print(f"Success: {result.success}")
    assert result.success
    assert "Test with markdown" in result.stdout
    print("✓ Markdown test passed\n")

def test_array_command():
    """Test command from array."""
    print("Testing array command...")
    result = execute_shell(["echo", "Array", "test"])
    print(f"Command: {result.command}")
    print(f"Stdout: {result.stdout.strip()}")
    print(f"Success: {result.success}")
    assert result.success
    print("✓ Array command test passed\n")

def test_failed_command():
    """Test command that fails."""
    print("Testing failed command...")
    result = execute_shell("ls /nonexistent_directory_12345")
    print(f"Command: {result.command}")
    print(f"Success: {result.success}")
    print(f"Returncode: {result.returncode}")
    print(f"Stderr: {result.stderr[:50]}...")
    assert not result.success
    assert result.returncode != 0
    print("✓ Failed command test passed\n")

def test_pydantic_model():
    """Test Pydantic model serialization."""
    print("Testing Pydantic model...")
    result = execute_shell("echo 'Pydantic test'")
    json_data = result.model_dump()
    print(f"JSON output: {json_data}")
    assert 'command' in json_data
    assert 'stdout' in json_data
    assert 'success' in json_data
    print("✓ Pydantic model test passed\n")

if __name__ == "__main__":
    print("=" * 50)
    print("Running secure_shell tests")
    print("=" * 50 + "\n")
    
    try:
        test_basic_command()
        test_markdown_wrapped()
        test_array_command()
        test_failed_command()
        test_pydantic_model()
        
        print("=" * 50)
        print("All tests passed! ✓")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
