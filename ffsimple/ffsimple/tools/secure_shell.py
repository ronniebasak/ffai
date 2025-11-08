"""Secure shell execution utilities with Pydantic response models."""

import re
import subprocess
import sys
import time
from typing import Union

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from ffsimple.deps.deps import Deps

class ShellResponse(BaseModel):
    """Response model for shell command execution (Pydantic V2 format)."""
    
    command: str = Field(
        ...,
        description="The actual command executed after trimming markdown"
    )
    stdout: str = Field(
        default="",
        description="Standard output from the command"
    )
    stderr: str = Field(
        default="",
        description="Standard error from the command"
    )
    returncode: int = Field(
        ...,
        description="Exit code of the process"
    )
    success: bool = Field(
        ...,
        description="Whether the command executed successfully (returncode == 0)"
    )
    execution_time: float = Field(
        ...,
        description="Time taken to execute the command in seconds"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "command": "echo 'Hello World'",
                    "stdout": "Hello World\n",
                    "stderr": "",
                    "returncode": 0,
                    "success": True,
                    "execution_time": 0.015
                }
            ]
        },
        "arbitrary_types_allowed": True,
        "allow_partial": True
    }


def _trim_markdown(command: str) -> str:
    """
    Trim markdown code fence identifiers from command string.
    
    Removes code blocks like:
    - ```bash ... ```
    - ```sh ... ```
    - ```shell ... ```
    - ``` ... ```
    
    Args:
        command: Command string potentially wrapped in markdown
        
    Returns:
        Cleaned command string
    """
    # Remove leading code fence with optional language identifier
    command = re.sub(r'^```(?:bash|sh|shell)?\s*\n?', '', command, flags=re.MULTILINE)
    
    # Remove trailing code fence
    command = re.sub(r'\n?```\s*$', '', command, flags=re.MULTILINE)
    
    # Strip leading/trailing whitespace
    return command.strip()


def execute_shell(
    ctx: RunContext[Deps],
    command: Union[str, list[str]],
    timeout: float = 30.0,
    shell: bool = True
) -> ShellResponse:
    """
    Execute a shell command and return structured response.
    
    Args:
        command: Shell script as string or array of command parts
        timeout: Maximum execution time in seconds (default: 30.0)
        shell: Whether to execute through shell (default: True)
        
    Returns:
        ShellResponse containing execution results
        
    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout
        
    Examples:
        >>> # Execute from string
        >>> result = execute_shell("echo 'Hello'")
        >>> print(result.stdout)
        Hello
        
        >>> # Execute from markdown-wrapped string
        >>> result = execute_shell("```bash\\nls -la\\n```")
        >>> print(result.success)
        True
        
        >>> # Execute from array
        >>> result = execute_shell(["ls", "-la"])
        >>> print(result.returncode)
        0
    """
    # Convert list to string if needed
    if isinstance(command, list):
        command_str = " ".join(command)
    else:
        command_str = command
    
    # Trim markdown identifiers
    cleaned_command = _trim_markdown(command_str)
    
    # Log the input command to stdout
    print(f"\n[SHELL] Executing command: {cleaned_command}", file=sys.stdout, flush=True)
    print("-" * 80, file=sys.stdout, flush=True)
    
    # Track execution time
    start_time = time.time()
    
    try:
        # Execute the command with streaming output
        process = subprocess.Popen(
            cleaned_command,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            bufsize=1,  # Line buffered
            universal_newlines=True
        )
        
        # Capture output while streaming to stdout
        stdout_lines = []
        stderr_lines = []
        
        try:
            # Wait for process to complete with timeout
            stdout_data, stderr_data = process.communicate(timeout=timeout)
            
            # Log streaming output to stdout
            if stdout_data:
                print(stdout_data, end='', file=sys.stdout, flush=True)
                stdout_lines.append(stdout_data)
            
            if stderr_data:
                print(f"[STDERR] {stderr_data}", end='', file=sys.stderr, flush=True)
                stderr_lines.append(stderr_data)
            
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_data, stderr_data = process.communicate()
            
            if stdout_data:
                stdout_lines.append(stdout_data)
            if stderr_data:
                stderr_lines.append(stderr_data)
            
            execution_time = time.time() - start_time
            print(f"\n[SHELL] Command timed out after {timeout} seconds", file=sys.stdout, flush=True)
            print("=" * 80, file=sys.stdout, flush=True)
            
            return ShellResponse(
                command=cleaned_command,
                stdout=''.join(stdout_lines),
                stderr=f"Command timed out after {timeout} seconds\n{''.join(stderr_lines)}",
                returncode=-1,
                success=False,
                execution_time=execution_time
            )
        
        execution_time = time.time() - start_time
        returncode = process.returncode
        
        # Log completion
        print(f"\n[SHELL] Command completed with exit code: {returncode}", file=sys.stdout, flush=True)
        print("=" * 80, file=sys.stdout, flush=True)
        
        return ShellResponse(
            command=cleaned_command,
            stdout=''.join(stdout_lines),
            stderr=''.join(stderr_lines),
            returncode=returncode,
            success=returncode == 0,
            execution_time=execution_time
        )
        
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"Execution error: {str(e)}"
        
        print(f"\n[SHELL] {error_msg}", file=sys.stdout, flush=True)
        print("=" * 80, file=sys.stdout, flush=True)
        
        return ShellResponse(
            command=cleaned_command,
            stdout="",
            stderr=error_msg,
            returncode=-1,
            success=False,
            execution_time=execution_time
        )
