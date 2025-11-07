"""Secure shell execution utilities with Pydantic response models."""

import re
import subprocess
import time
from typing import Union

from pydantic import BaseModel, Field


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
        }
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
    
    # Track execution time
    start_time = time.time()
    
    try:
        # Execute the command
        result = subprocess.run(
            cleaned_command,
            shell=shell,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout,
            check=False  # Don't raise exception on non-zero exit
        )
        
        execution_time = time.time() - start_time
        
        return ShellResponse(
            command=cleaned_command,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            success=result.returncode == 0,
            execution_time=execution_time
        )
        
    except subprocess.TimeoutExpired as e:
        execution_time = time.time() - start_time
        
        return ShellResponse(
            command=cleaned_command,
            stdout=e.stdout.decode('utf-8') if e.stdout else "",
            stderr=f"Command timed out after {timeout} seconds",
            returncode=-1,
            success=False,
            execution_time=execution_time
        )
        
    except Exception as e:
        execution_time = time.time() - start_time
        
        return ShellResponse(
            command=cleaned_command,
            stdout="",
            stderr=f"Execution error: {str(e)}",
            returncode=-1,
            success=False,
            execution_time=execution_time
        )
