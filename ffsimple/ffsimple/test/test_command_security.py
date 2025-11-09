"""Tests for command security and classification in secure_shell module."""

import pytest
from ffsimple.tools.secure_shell import (
    check_root_user,
    classify_command,
    check_command_safety,
    SAFE_COMMANDS,
    DANGEROUS_COMMANDS,
    BLOCKED_COMMANDS
)


class TestRootDetection:
    """Test root user detection."""
    
    def test_sudo_prefix(self):
        """Test detection of sudo commands."""
        is_root, warning = check_root_user("sudo rm -rf /")
        assert is_root is True
        assert "ROOT WARNING" in warning
        assert "elevated privileges" in warning
    
    def test_su_prefix(self):
        """Test detection of su commands."""
        is_root, warning = check_root_user("su root")
        assert is_root is True
        assert "ROOT WARNING" in warning
    
    def test_doas_prefix(self):
        """Test detection of doas commands."""
        is_root, warning = check_root_user("doas reboot")
        assert is_root is True
        assert "ROOT WARNING" in warning
    
    def test_normal_command(self):
        """Test normal commands are not flagged as root."""
        is_root, warning = check_root_user("ls -la")
        assert is_root is False
        assert warning == ""


class TestCommandClassification:
    """Test command classification logic."""
    
    def test_safe_video_commands(self):
        """Test video operation commands are classified as safe."""
        safe_video_commands = [
            "ffmpeg -i input.mp4 output.mp4",
            "ffprobe video.mp4",
            "mediainfo file.mkv"
        ]
        for cmd in safe_video_commands:
            category, reason = classify_command(cmd)
            assert category == "SAFE", f"Command '{cmd}' should be SAFE"
    
    def test_safe_read_commands(self):
        """Test read-only commands are classified as safe."""
        safe_read_commands = [
            "ls -la",
            "cat file.txt",
            "grep pattern file.txt",
            "find . -name '*.mp4'"
        ]
        for cmd in safe_read_commands:
            category, reason = classify_command(cmd)
            assert category == "SAFE", f"Command '{cmd}' should be SAFE"
    
    def test_dangerous_deletion_commands(self):
        """Test deletion commands are classified as dangerous."""
        dangerous_delete_commands = [
            "rm file.txt",
            "rm -rf directory/",
            "rmdir folder",
            "unlink file.mp4"
        ]
        for cmd in dangerous_delete_commands:
            category, reason = classify_command(cmd)
            assert category == "DANGEROUS", f"Command '{cmd}' should be DANGEROUS"
            assert "deletion" in reason.lower()
    
    def test_dangerous_permission_commands(self):
        """Test permission modification commands are classified as dangerous."""
        dangerous_perm_commands = [
            "chmod 777 file.sh",
            "chown user:group file.txt",
            "chgrp group file.txt"
        ]
        for cmd in dangerous_perm_commands:
            category, reason = classify_command(cmd)
            assert category == "DANGEROUS", f"Command '{cmd}' should be DANGEROUS"
            assert "permission" in reason.lower()
    
    def test_blocked_system_commands(self):
        """Test system-critical commands are blocked."""
        blocked_system_commands = [
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "fdisk /dev/sda",
            "shutdown -h now",
            "reboot"
        ]
        for cmd in blocked_system_commands:
            category, reason = classify_command(cmd)
            assert category == "BLOCKED", f"Command '{cmd}' should be BLOCKED"
            assert "blocked" in reason.lower()
    
    def test_blocked_sudo_commands(self):
        """Test sudo commands are blocked."""
        category, reason = classify_command("sudo apt-get install package")
        assert category == "BLOCKED"
        assert "sudo" in reason.lower()
    
    def test_unknown_commands_are_dangerous(self):
        """Test unknown commands default to dangerous."""
        category, reason = classify_command("unknowncommand --flag")
        assert category == "DANGEROUS"
        assert "unknown" in reason.lower()


class TestCommandSafety:
    """Test combined safety checks."""
    
    def test_safe_command_no_warning(self):
        """Test safe commands have no warnings."""
        requires_approval, is_blocked, warning = check_command_safety("ls -la")
        assert requires_approval is False
        assert is_blocked is False
        assert warning == ""
    
    def test_dangerous_command_requires_approval(self):
        """Test dangerous commands require approval."""
        requires_approval, is_blocked, warning = check_command_safety("rm file.txt")
        assert requires_approval is True
        assert is_blocked is False
        assert "REQUIRES APPROVAL" in warning
        assert "deletion" in warning.lower()
    
    def test_blocked_command_is_blocked(self):
        """Test blocked commands are blocked."""
        requires_approval, is_blocked, warning = check_command_safety("sudo rm -rf /")
        assert is_blocked is True
        assert "BLOCKED" in warning
    
    def test_safe_command_with_sudo_requires_approval(self):
        """Test even safe commands with sudo require approval."""
        requires_approval, is_blocked, warning = check_command_safety("sudo ls")
        assert is_blocked is True  # sudo itself is blocked
        assert "BLOCKED" in warning
    
    def test_ffmpeg_is_safe(self):
        """Test ffmpeg commands are safe for video processing."""
        requires_approval, is_blocked, warning = check_command_safety(
            "ffmpeg -i input.mp4 -vcodec libx264 -crf 23 output.mp4"
        )
        assert requires_approval is False
        assert is_blocked is False
        assert warning == ""
    
    def test_package_install_is_dangerous(self):
        """Test package installation requires approval."""
        requires_approval, is_blocked, warning = check_command_safety("pip install requests")
        assert requires_approval is True
        assert is_blocked is False
        assert "package management" in warning.lower()


class TestCommandLists:
    """Test the command list definitions."""
    
    def test_safe_commands_list(self):
        """Test SAFE_COMMANDS list is properly defined."""
        assert "ffmpeg" in SAFE_COMMANDS
        assert "ffprobe" in SAFE_COMMANDS
        assert "ls" in SAFE_COMMANDS
        assert "cat" in SAFE_COMMANDS
    
    def test_dangerous_commands_list(self):
        """Test DANGEROUS_COMMANDS list is properly defined."""
        assert "rm" in DANGEROUS_COMMANDS
        assert "chmod" in DANGEROUS_COMMANDS
        assert "mv" in DANGEROUS_COMMANDS
        assert "pip" in DANGEROUS_COMMANDS
    
    def test_blocked_commands_list(self):
        """Test BLOCKED_COMMANDS list is properly defined."""
        assert "sudo" in BLOCKED_COMMANDS
        assert "dd" in BLOCKED_COMMANDS
        assert "mkfs" in BLOCKED_COMMANDS
        assert "shutdown" in BLOCKED_COMMANDS
        assert "reboot" in BLOCKED_COMMANDS


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_empty_command(self):
        """Test empty command is handled safely."""
        category, reason = classify_command("")
        assert category == "SAFE"
    
    def test_command_with_pipes(self):
        """Test commands with pipes are classified by first command."""
        category, reason = classify_command("ls -la | grep mp4")
        assert category == "SAFE"  # ls is safe
    
    def test_command_with_multiple_spaces(self):
        """Test commands with multiple spaces."""
        category, reason = classify_command("ffmpeg    -i    input.mp4")
        assert category == "SAFE"
    
    def test_case_insensitive_matching(self):
        """Test command matching is case-insensitive."""
        category1, _ = classify_command("RM file.txt")
        category2, _ = classify_command("rm file.txt")
        assert category1 == category2 == "DANGEROUS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
