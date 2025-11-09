"""ASCII art banner for FFSimple with gradient effects."""

from rich.console import Console
from rich.text import Text


def get_ascii_banner() -> Text:
    """Generate ASCII art banner with gradient for FFSimple.
    
    Returns:
        Rich Text object with styled ASCII art
    """
    banner = Text()
    
    # ASCII art for "FFSimple" with gradient colors (cyan -> magenta)
    lines = [
        "███████╗███████╗███████╗██╗███╗   ███╗██████╗ ██╗     ███████╗",
        "██╔════╝██╔════╝██╔════╝██║████╗ ████║██╔══██╗██║     ██╔════╝",
        "█████╗  █████╗  ███████╗██║██╔████╔██║██████╔╝██║     █████╗  ",
        "██╔══╝  ██╔══╝  ╚════██║██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝  ",
        "██║     ██║     ███████║██║██║ ╚═╝ ██║██║     ███████╗███████╗",
        "╚═╝     ╚═╝     ╚══════╝╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝",
    ]
    
    # Gradient colors from cyan to magenta
    colors = ["cyan", "bright_cyan", "blue", "bright_blue", "magenta", "bright_magenta"]
    
    # Apply gradient to each line
    for i, line in enumerate(lines):
        color = colors[i % len(colors)]
        banner.append(line + "\n", style=f"bold {color}")
    
    # Add subtitle with yellow/gold color
    banner.append("\n          ", style="")
    banner.append("The Agentic Video Editor", style="bold yellow")
    banner.append("\n", style="")
    
    return banner


def display_ascii_banner(console: Console = None):
    """Display the ASCII art banner.
    
    Args:
        console: Rich Console instance. If None, creates a new one.
    """
    if console is None:
        console = Console()
    
    banner = get_ascii_banner()
    console.print(banner)
    console.print()
