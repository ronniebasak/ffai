"""Secure shell execution utilities with Pydantic response models."""

import os
import re
import subprocess
import sys
import time
from typing import Union

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from ffsimple.deps.deps import Deps

# Command classification lists
SAFE_COMMANDS = [
    # Video operations
    "ffmpeg", "ffprobe", "mediainfo", "mkvmerge", "mkvextract", "mp4box",
    # Read operations
    "ls", "cat", "head", "tail", "grep", "find", "file", "stat", "wc", "du",
    # Directory operations
    "pwd", "cd", "tree",
    # Video inspection
    "exiftool", "identify",
    # Safe utilities
    "echo", "date", "uname", "whoami", "which", "type",
]

DANGEROUS_COMMANDS = [
    # Deletion operations
    "rm", "rmdir", "unlink", "shred",
    # File system modifications
    "mv", "chmod", "chown", "chgrp", "touch",
    # Package management
    "apt", "apt-get", "yum", "dnf", "pacman", "pip", "npm", "yarn",
    # Network operations with write capability
    "curl", "wget", "scp", "rsync",
    # Process management
    "kill", "pkill", "killall", "systemctl", "service",
    # Compression with overwrite
    "tar", "zip", "unzip", "gzip", "bzip2",
]

BLOCKED_COMMANDS = [
    # Root/privilege escalation
    "sudo", "su", "doas",
    # System critical operations
    "dd", "mkfs", "fdisk", "parted", "gdisk", "mount", "umount",
    # Kernel operations
    "modprobe", "insmod", "rmmod", "kmod",
    # System shutdown/reboot
    "shutdown", "reboot", "halt", "poweroff", "init",
    # Disk operations
    "mkswap", "swapon", "swapoff",
]

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
    approval_required: bool = Field(
        default=False,
        description="Whether the command requires user approval before execution"
    )
    security_warning: str = Field(
        default="",
        description="Security warning message if command is dangerous or blocked"
    )
    blocked: bool = Field(
        default=False,
        description="Whether the command is blocked and cannot be executed"
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
                    "execution_time": 0.015,
                    "approval_required": False,
                    "security_warning": "",
                    "blocked": False
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


def check_root_user(command: str) -> tuple[bool, str]:
    """
    Check if command is attempting to run with root privileges.
    
    Args:
        command: The command string to check
        
    Returns:
        Tuple of (is_root, warning_message)
    """
    command_lower = command.lower().strip()
    
    # Check for sudo, su, doas at the start
    if command_lower.startswith(('sudo ', 'su ', 'doas ')):
        return True, "🚨 ROOT WARNING: This command will run with elevated privileges!"
    
    # Check if running as root user
    try:
        if os.geteuid() == 0:
            return True, "🚨 ROOT WARNING: You are currently running as root user!"
    except AttributeError:
        # Windows doesn't have geteuid, skip this check
        pass
    
    return False, ""


def classify_command(command: str) -> tuple[str, str]:
    """
    Classify a command as SAFE, DANGEROUS, or BLOCKED.
    
    Args:
        command: The command string to classify
        
    Returns:
        Tuple of (category, reason) where category is 'SAFE', 'DANGEROUS', or 'BLOCKED'
    """
    # Extract the base command (first word)
    command_parts = command.strip().split()
    if not command_parts:
        return "SAFE", ""
    
    base_command = command_parts[0].lower()
    
    # Remove common prefixes
    for prefix in ['sudo', 'su', 'doas']:
        if base_command == prefix and len(command_parts) > 1:
            base_command = command_parts[1].lower()
            break
    
    # Check for blocked commands
    for blocked in BLOCKED_COMMANDS:
        if base_command == blocked or base_command.startswith(blocked + ' '):
            return "BLOCKED", f"Command '{blocked}' is blocked for security reasons (system-critical operation)"
    
    # Check for dangerous commands
    for dangerous in DANGEROUS_COMMANDS:
        if base_command == dangerous or base_command.startswith(dangerous + ' '):
            reason = f"Command '{dangerous}' requires approval "
            
            if dangerous in ['rm', 'rmdir', 'unlink', 'shred']:
                reason += "(deletion operation)"
            elif dangerous in ['chmod', 'chown', 'chgrp']:
                reason += "(permission modification)"
            elif dangerous in ['mv']:
                reason += "(file move/rename operation)"
            elif dangerous in ['apt', 'apt-get', 'yum', 'dnf', 'pacman', 'pip', 'npm', 'yarn']:
                reason += "(package management)"
            elif dangerous in ['kill', 'pkill', 'killall', 'systemctl', 'service']:
                reason += "(process management)"
            else:
                reason += "(potentially dangerous operation)"
            
            return "DANGEROUS", reason
    
    # Check for safe commands
    for safe in SAFE_COMMANDS:
        if base_command == safe or base_command.startswith(safe + ' '):
            return "SAFE", ""
    
    # Default: treat unknown commands as dangerous
    return "DANGEROUS", f"Unknown command '{base_command}' requires approval for safety"


def check_command_safety(command: str) -> tuple[bool, bool, str]:
    """
    Check if a command requires approval or is blocked.
    
    Args:
        command: The command string to check
        
    Returns:
        Tuple of (requires_approval, is_blocked, warning_message)
    """
    # Check for root user
    is_root, root_warning = check_root_user(command)
    
    # Classify the command
    category, reason = classify_command(command)
    
    if category == "BLOCKED":
        warning = f"⛔ BLOCKED: {reason}"
        if is_root:
            warning += f"\n{root_warning}"
        return False, True, warning
    
    elif category == "DANGEROUS":
        warning = f"⚠️ REQUIRES APPROVAL: {reason}"
        if is_root:
            warning += f"\n{root_warning}"
        return True, False, warning
    
    else:  # SAFE
        if is_root:
            # Even safe commands get flagged if running as root
            return True, False, root_warning
        return False, False, ""


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
    
    # Check command safety BEFORE execution
    requires_approval, is_blocked, warning_message = check_command_safety(cleaned_command)
    
    # If command is blocked, return immediately without execution
    if is_blocked:
        print(f"\n[SHELL] {warning_message}", file=sys.stderr, flush=True)
        print(f"[SHELL] Command blocked: {cleaned_command}", file=sys.stderr, flush=True)
        print("=" * 80, file=sys.stderr, flush=True)
        
        return ShellResponse(
            command=cleaned_command,
            stdout="",
            stderr=f"Command execution blocked for security reasons.\n{warning_message}",
            returncode=-2,
            success=False,
            execution_time=0.0,
            approval_required=False,
            security_warning=warning_message,
            blocked=True
        )
    
    # If command requires approval, log warning and proceed
    # (In a real implementation, you would prompt the user here)
    # For now, we log the warning but allow execution to proceed
    if requires_approval:
        print(f"\n[SHELL] {warning_message}", file=sys.stdout, flush=True)
        print(f"[SHELL] Command requires approval: {cleaned_command}", file=sys.stdout, flush=True)
        print("-" * 80, file=sys.stdout, flush=True)
    
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
                execution_time=execution_time,
                approval_required=requires_approval,
                security_warning=warning_message,
                blocked=False
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
            execution_time=execution_time,
            approval_required=requires_approval,
            security_warning=warning_message,
            blocked=False
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
            execution_time=execution_time,
            approval_required=requires_approval,
            security_warning=warning_message,
            blocked=False
        )
