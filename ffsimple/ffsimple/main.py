"""Enhanced CLI with Rich library for beautiful output and streaming agent thoughts.

Run with:
    uv run -m ffsimple.main
"""

from __future__ import annotations as _annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

import logfire
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.markdown import Markdown
from rich.table import Table
from rich.spinner import Spinner
from rich.layout import Layout
from rich.prompt import Prompt
from rich import box
from rich.syntax import Syntax


class QuitChatException(Exception):
    """Exception raised when the quit_chat tool is called."""
    pass


from httpx import AsyncClient
from pydantic import BaseModel

from pydantic_ai import Agent, RunContext
from pydantic_ai.result import StreamedRunResult
from textwrap import dedent
from enum import Enum
from .tools.secure_shell import execute_shell
from .deps.deps import Deps
from .config import load_config, ConfigManager
from .ascii_art import display_ascii_banner

# Initialize Rich console
console = Console()

# 'if-token-present' means nothing will be sent (and the example will work) if you don't have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()


class OrcResponseStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INDETERMINATE = "INDETERMINATE"


class OrcResponse(BaseModel):
    response: str
    status: OrcResponseStatus 


def create_agent(model_string: str, startup_context: str = "") -> Agent:
    """Create an agent with the specified model.
    
    Args:
        model_string: The model string (e.g., "groq:llama3-70b-8192")
        startup_context: Optional startup context to include in instructions
    """
    base_instructions = dedent("""You are an video editor agent, your job is to look at the query and run
                    If you think certain details are lacking, you can directly use the ask_user tool to ask questions to the user.
                    Before asking the user questions such as which file etc, you can run ls -la using the shell or scan for video files to present which files they want converted
                    Respond with SUCCESS only if the objective has been achieved, else return INDETERMINATE
               
                    NOTE: in shell scripts, we need to escape/quote parameters that has spaces in them
                    
                    If you want to show info mid-process, use the tool show_passive_info_to_user, if you want some inputs use show_info_and_ask_question
                    show_info_and_ask_question: Use when you expect a response from the user
                    show_passive_info_to_user: Use when you need to show info to the user, and then need to perform other tasks
                    However, if the response is terminal or conclusive, respond with SUCCESS and embed the message in the response field.
                    When finished, print detailed info on what has been achieved (resolution changes, compression ratio among others, think what to present)
                    if we detect any incompatibilities (such as resolution, framerate etc) present user with options such as letterboxing, 60fps vs 30fps, try and pick best option beforehand
                    only if the user confirms, you can use the executor agent""")
    
    # Append startup context if provided
    if startup_context:
        full_instructions = base_instructions + "\n\n" + startup_context
    else:
        full_instructions = base_instructions
    
    return Agent(
        model_string,
        instructions=full_instructions,
        output_type=OrcResponse,
        deps_type=Deps,
        retries=2,
    )



def register_tools(agent: Agent):
    """Register tools with the agent."""
    
    @agent.tool
    async def show_info_and_ask_question(ctx: RunContext[Deps], prompt: str) -> str:
        """Prompt a user for input: Takes a question, asks clarification from the user and returns it. You should use it only when user input is required"""
        console.print(Panel(
            prompt,
            title="[bold yellow]🤔 Agent Question[/bold yellow]",
            border_style="yellow",
            box=box.ROUNDED
        ))
        a = await asyncio.to_thread(Prompt.ask, "[bold cyan]Your response[/bold cyan]")
        return a

    agent.tool(execute_shell)

    @agent.tool
    async def show_passive_info_to_user(ctx: RunContext[Deps], prompt: str) -> str:
        """Displays info to the user: Takes a prompt and displays it to the user in a nice and friendly way, user input is ignored"""
        console.print(Panel(
            prompt,
            title="[bold blue]ℹ️  Agent Info[/bold blue]",
            border_style="blue",
            box=box.ROUNDED
        ))
        a = await asyncio.to_thread(Prompt.ask, "[bold cyan]Press Enter to continue[/bold cyan]", default="ok")
        return "Continue your execution"

    @agent.tool
    async def quit_chat(ctx: RunContext[Deps], reason: str = "") -> str:
        """End the conversation. Use this when the user wants to exit or the task is fully complete."""
        raise QuitChatException(reason)

    # NOTE: Removed system_prompt that was calling execute_shell on every agent run
    # This was causing double execution issues. The agent can call execute_shell
    # as a tool when it needs directory information instead.


class LatLng(BaseModel):
    lat: float
    lng: float


def display_welcome_banner():
    """Display a beautiful welcome banner"""
    # Display ASCII art banner first
    display_ascii_banner(console)
    
    banner = Text()
    banner.append("🎬 ", style="bold yellow")
    banner.append("FFSimple Video Editor Agent", style="bold magenta")
    banner.append(" 🎬", style="bold yellow")
    
    console.print(Panel(
        banner,
        box=box.DOUBLE,
        border_style="magenta",
        padding=(1, 2)
    ))
    
    info_text = Text()
    info_text.append("Welcome! I'm your AI video editing assistant.\n", style="bold green")
    info_text.append("I can help you with video conversion, editing, and analysis.\n\n", style="green")
    
    # Slash Commands Section
    info_text.append("💬 Slash Commands (use in chat):\n", style="bold cyan")
    info_text.append("  • ", style="cyan")
    info_text.append("/help", style="bold yellow")
    info_text.append("          Show available commands and usage tips\n", style="cyan")
    info_text.append("  • ", style="cyan")
    info_text.append("/config", style="bold yellow")
    info_text.append("        Open interactive configuration menu\n", style="cyan")
    info_text.append("  • ", style="cyan")
    info_text.append("/model", style="bold yellow")
    info_text.append("         View or change AI model (e.g., /model groq llama3-70b-8192)\n", style="cyan")
    info_text.append("  • ", style="cyan")
    info_text.append("/quit", style="bold yellow")
    info_text.append("          Exit the application\n\n", style="cyan")
    
    # CLI Arguments Section
    info_text.append("⚙️  CLI Arguments (use on startup):\n", style="bold magenta")
    info_text.append("  • ", style="magenta")
    info_text.append("--config", style="bold yellow")
    info_text.append("           Open configuration menu on startup\n", style="magenta")
    info_text.append("  • ", style="magenta")
    info_text.append("--provider", style="bold yellow")
    info_text.append(" <name>   Override provider (openrouter, groq, ollama)\n", style="magenta")
    info_text.append("  • ", style="magenta")
    info_text.append("--model", style="bold yellow")
    info_text.append(" <name>      Override model for this session\n", style="magenta")
    info_text.append("  • ", style="magenta")
    info_text.append("--refresh-models", style="bold yellow")
    info_text.append("  Force refresh model catalog\n\n", style="magenta")
    
    # Keyboard Shortcuts Section
    info_text.append("⌨️  Keyboard Shortcuts:\n", style="bold red")
    info_text.append("  • Press ", style="red")
    info_text.append("Ctrl+C", style="bold yellow")
    info_text.append(" to interrupt/cancel current operation\n", style="red")
    
    console.print(Panel(
        info_text,
        title="[bold cyan]Getting Started[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()


async def handle_slash_command(command: str, config_manager: ConfigManager, current_provider: str, current_model: str) -> tuple[bool, str | None, str | None, Agent | None]:
    """Handle slash commands in chat.
    
    Returns:
        Tuple of (should_continue, new_provider, new_model, new_agent)
        - should_continue: False if should exit the loop
        - new_provider: Updated provider if changed
        - new_model: Updated model if changed  
        - new_agent: New agent if model changed
    """
    command = command.strip().lower()
    parts = command.split()
    cmd = parts[0]
    
    if cmd == '/quit':
        console.print(Panel(
            "[bold green]Thank you for using FFSimple! Goodbye! 👋[/bold green]",
            border_style="green",
            box=box.ROUNDED
        ))
        return False, None, None, None
    
    elif cmd == '/help':
        help_text = Text()
        help_text.append("Available Commands:\n\n", style="bold cyan")
        help_text.append("  /help", style="bold yellow")
        help_text.append("     - Show this help message\n", style="white")
        help_text.append("  /config", style="bold yellow")
        help_text.append("   - Open interactive configuration menu\n", style="white")
        help_text.append("  /model", style="bold yellow")
        help_text.append("    - View current model or change it\n", style="white")
        help_text.append("            Usage: /model [provider] [model]\n", style="dim")
        help_text.append("            Example: /model groq llama3-70b-8192\n", style="dim")
        help_text.append("  /quit", style="bold yellow")
        help_text.append("     - Exit the application\n\n", style="white")
        help_text.append("Video Editing Tips:\n\n", style="bold cyan")
        help_text.append("  • Describe what you want clearly\n", style="green")
        help_text.append("  • Mention specific resolutions, formats, codecs\n", style="green")
        help_text.append("  • The agent will ask for clarification if needed\n", style="green")
        
        console.print(Panel(
            help_text,
            title="[bold cyan]📖 Help & Commands[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        ))
        return True, None, None, None
    
    elif cmd == '/config':
        console.print()
        await config_manager.interactive_config_menu()
        console.print()
        
        # Get updated config
        new_provider, new_model, api_key, ollama_base_url = config_manager.get_model_config()
        
        # Set API key
        if api_key:
            if new_provider == "groq":
                os.environ["GROQ_API_KEY"] = api_key
            elif new_provider == "openrouter":
                os.environ["OPENROUTER_API_KEY"] = api_key
        
        # Set Ollama base URL if using Ollama
        if new_provider == "ollama":
            os.environ["OLLAMA_BASE_URL"] = ollama_base_url
        
        # Create new agent if provider/model changed
        if new_provider != current_provider or new_model != current_model:
            model_string = f"{new_provider}:{new_model}"
            # Note: When switching models mid-session, we don't re-gather startup context
            # as it was already gathered once at the beginning
            new_agent = create_agent(model_string)
            register_tools(new_agent)
            
            console.print(Panel(
                f"[bold green]✓ Switched to:[/bold green] [cyan]{new_provider}[/cyan] / [cyan]{new_model}[/cyan]",
                border_style="green",
                box=box.ROUNDED
            ))
            
            return True, new_provider, new_model, new_agent
        
        return True, None, None, None
    
    elif cmd == '/model':
        if len(parts) == 1:
            # Just show current model
            console.print(Panel(
                f"[bold]Current Configuration:[/bold]\n\n"
                f"Provider: [cyan]{current_provider}[/cyan]\n"
                f"Model: [cyan]{current_model}[/cyan]\n\n"
                f"[dim]To change: /model <provider> <model>[/dim]",
                title="[bold cyan]🤖 Model Info[/bold cyan]",
                border_style="cyan",
                box=box.ROUNDED
            ))
            return True, None, None, None
        
        elif len(parts) >= 3:
            # Change model
            new_provider = parts[1].lower()
            new_model = ' '.join(parts[2:])
            
            if new_provider not in ['openrouter', 'groq', 'ollama']:
                console.print(Panel(
                    f"[bold red]Invalid provider:[/bold red] {new_provider}\n"
                    f"Valid providers: openrouter, groq, ollama",
                    border_style="red",
                    box=box.ROUNDED
                ))
                return True, None, None, None
            
            # Get API key and Ollama base URL for the provider
            api_key = config_manager.config.get("api_keys", {}).get(new_provider)
            ollama_base_url = config_manager.config.get("ollama_base_url", "http://localhost:11434/v1")
            
            if not api_key and new_provider != "ollama":
                console.print(Panel(
                    f"[bold yellow]No API key found for {new_provider}[/bold yellow]\n"
                    f"Please run /config to set up API keys.",
                    border_style="yellow",
                    box=box.ROUNDED
                ))
                return True, None, None, None
            
            # Set API key
            if api_key:
                if new_provider == "groq":
                    os.environ["GROQ_API_KEY"] = api_key
                elif new_provider == "openrouter":
                    os.environ["OPENROUTER_API_KEY"] = api_key
            
            # Set Ollama base URL if using Ollama
            if new_provider == "ollama":
                os.environ["OLLAMA_BASE_URL"] = ollama_base_url
            
            # Create new agent
            model_string = f"{new_provider}:{new_model}"
            # Note: When switching models mid-session, we don't re-gather startup context
            # as it was already gathered once at the beginning
            new_agent = create_agent(model_string)
            register_tools(new_agent)
            
            console.print(Panel(
                f"[bold green]✓ Model changed to:[/bold green] [cyan]{new_provider}:{new_model}[/cyan]\n\n"
                f"[dim]This change is for the current session only.\n"
                f"To make it permanent, use /config[/dim]",
                border_style="green",
                box=box.ROUNDED
            ))
            
            return True, new_provider, new_model, new_agent
        
        else:
            console.print(Panel(
                "[bold red]Invalid usage[/bold red]\n\n"
                "Usage: /model [provider] [model]\n"
                "Example: /model groq llama3-70b-8192",
                border_style="red",
                box=box.ROUNDED
            ))
            return True, None, None, None
    
    else:
        console.print(Panel(
            f"[bold red]Unknown command:[/bold red] {cmd}\n\n"
            f"Type [bold yellow]/help[/bold yellow] to see available commands.",
            border_style="red",
            box=box.ROUNDED
        ))
        return True, None, None, None


async def stream_agent_response(agent: Agent, query: str, deps: Deps, message_history=None):
    """Stream agent's thoughts and response in real-time"""
    
    # Create a layout for streaming thoughts
    thought_text = Text()
    response_text = Text()
    
    console.print(Panel(
        f"[bold cyan]{query}[/bold cyan]",
        title="[bold white]📝 Your Query[/bold white]",
        border_style="white",
        box=box.ROUNDED
    ))
    console.print()
    
    # Show thinking indicator
    with console.status("[bold yellow]🤔 Agent is thinking...[/bold yellow]", spinner="dots"):
        await asyncio.sleep(0.5)  # Brief pause for effect
    
    console.print(Panel(
        "[bold yellow]💭 Agent's Thought Process[/bold yellow]",
        border_style="yellow",
        box=box.ROUNDED
    ))
    
    # Stream the agent's response
    result = None
    all_messages = None
    try:
        async with agent.run_stream(query, deps=deps, message_history=message_history) as stream:
            thoughts_shown = False
            tool_calls = []
            
            if hasattr(stream, '__aiter__'):
                async for chunk in stream:
                    # Handle different types of streaming events
                    if hasattr(chunk, 'type'):
                        # Tool call events
                        if chunk.type == 'tool_call':
                            tool_calls.append(chunk)
                            console.print(f"  [dim]→ Calling tool: [bold cyan]{chunk.tool_name}[/bold cyan][/dim]")
                        
                        elif chunk.type == 'tool_result':
                            console.print(f"  [dim]✓ Tool completed[/dim]")
                    
                    # Stream text content
                    if hasattr(chunk, 'data'):
                        if not thoughts_shown:
                            thoughts_shown = True
                        # Print streaming text (you can customize this based on chunk content)
                        pass
        
            # Get final result
            result = await stream.get_output()
            all_messages = stream.all_messages()
            
    except Exception as e:
        console.print(f"[bold red]Error during streaming: {e}[/bold red]")
        # Don't fallback to re-running - this causes double execution
        # Just return None and let the error be visible
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        result = None
    
    console.print(result)
    
    # Display final response
    if result and result:
        status_color = {
            "SUCCESS": "green",
            "FAILURE": "red",
            "INDETERMINATE": "yellow"
        }.get(result.status, "white")
        
        status_emoji = {
            "SUCCESS": "✅",
            "FAILURE": "❌",
            "INDETERMINATE": "⏳"
        }.get(result.status, "ℹ️")
        
        console.print(Panel(
            f"[bold {status_color}]{result.response}[/bold {status_color}]",
            title=f"[bold {status_color}]{status_emoji} Agent Response - {result.status}[/bold {status_color}]",
            border_style=status_color,
            box=box.HEAVY
        ))
    
    return all_messages


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="FFSimple - AI-powered video editor agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ffsimple "convert video.mp4 to 1080p"
  ffsimple --config
  ffsimple --provider groq --model llama3-70b-8192 "your query"
  ffsimple --refresh-models
        """
    )
    
    parser.add_argument(
        "query",
        nargs="*",
        help="Your video editing query (optional if using --config)"
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Open interactive configuration menu"
    )
    parser.add_argument(
        "--provider",
        choices=["openrouter", "groq", "ollama"],
        help="Override the default provider for this run"
    )
    parser.add_argument(
        "--model",
        help="Override the default model for this run"
    )
    parser.add_argument(
        "--refresh-models",
        action="store_true",
        help="Force refresh the model catalog"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point with enhanced Rich CLI"""
    
    # Parse arguments
    args = parse_args()
    
    # Load configuration
    config_manager = await load_config()
    
    # Handle --config flag
    if args.config:
        await config_manager.interactive_config_menu()
        return
    
    # Handle --refresh-models flag
    if args.refresh_models:
        provider = args.provider or config_manager.config.get("provider")
        config_manager.refresh_model_catalog(provider, force=True)
        return
    
    # Get model configuration with optional overrides
    provider, model, api_key, ollama_base_url = config_manager.get_model_config(
        provider_override=args.provider,
        model_override=args.model
    )
    
    # Set API key as environment variable for pydantic-ai
    if api_key:
        if provider == "groq":
            os.environ["GROQ_API_KEY"] = api_key
        elif provider == "openrouter":
            os.environ["OPENROUTER_API_KEY"] = api_key
    
    # Set Ollama base URL as environment variable
    if provider == "ollama":
        os.environ["OLLAMA_BASE_URL"] = ollama_base_url
    
    # Construct model string for pydantic-ai
    model_string = f"{provider}:{model}"
    
    # Display welcome banner
    display_welcome_banner()
    
    # Show current configuration
    console.print(Panel(
        f"[bold]Using:[/bold] [cyan]{provider}[/cyan] / [cyan]{model}[/cyan]",
        border_style="dim",
        box=box.ROUNDED
    ))
    console.print()
    
    # Gather startup context once
    import subprocess
    startup_context_parts = []
    
    try:
        # Get current directory contents
        lsla_result = subprocess.run(
            ["ls", "-la"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if lsla_result.returncode == 0:
            startup_context_parts.append(f"---\nCurrent directory contents:\n{lsla_result.stdout}")
        
        # Get system info
        uname_result = subprocess.run(
            ["uname", "-a"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if uname_result.returncode == 0:
            startup_context_parts.append(f"---\nSystem info (uname -a):\n{uname_result.stdout}")
        
        # Get date/time
        date_result = subprocess.run(
            ["date"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if date_result.returncode == 0:
            startup_context_parts.append(f"---\nCurrent date/time:\n{date_result.stdout}")
    except Exception as e:
        console.print(f"[dim yellow]Note: Could not gather startup context: {e}[/dim yellow]")
    
    startup_context = "\n".join(startup_context_parts) if startup_context_parts else ""
    
    # Create agent with configured model and startup context
    agent = create_agent(model_string, startup_context=startup_context)
    register_tools(agent)
    
    # Get initial query from command-line arguments or prompt user
    if args.query:
        # Concatenate all arguments as the query
        query = ' '.join(args.query)
    else:
        # Prompt user for query with Rich
        query = await asyncio.to_thread(Prompt.ask, "[bold green]Enter your query[/bold green]")
    
    async with AsyncClient() as client:
        logfire.instrument_httpx(client, capture_all=True)
        deps = Deps(client=client)
        
        # Initialize message history to maintain context across follow-up queries
        message_history = None
        
        # Continuous conversation loop
        while True:
            try:
                # Check for slash commands
                if query.strip().startswith('/'):
                    should_continue, new_provider, new_model, new_agent = await handle_slash_command(
                        query, config_manager, provider, model
                    )
                    
                    if not should_continue:
                        break
                    
                    # Update agent if changed
                    if new_agent is not None:
                        agent = new_agent
                        provider = new_provider
                        model = new_model
                        # Reset message history when switching models
                        message_history = None
                    
                    # Prompt for next query
                    console.print()
                    query = await asyncio.to_thread(Prompt.ask, "[bold green]Enter your next query[/bold green]")
                    continue
                
                # Run the agent with streaming
                all_messages = await stream_agent_response(agent, query, deps, message_history)
                
                # Store message history for next iteration to maintain context
                if all_messages:
                    message_history = all_messages
                
                # Prompt for next query
                console.print()
                console.rule("[bold blue]Ready for next query[/bold blue]")
                console.print()
                query = await asyncio.to_thread(Prompt.ask, "[bold green]Enter your next query (or '/quit' to exit)[/bold green]")
                
            except QuitChatException as e:
                # quit_chat tool was called - exit immediately
                reason = str(e) if str(e) else "Task completed"
                console.print(Panel(
                    f"[bold green]{reason}\n\nGoodbye! 👋[/bold green]",
                    title="[bold green]✅ Session Ended[/bold green]",
                    border_style="green",
                    box=box.DOUBLE
                ))
                break
            except KeyboardInterrupt:
                console.print("\n")
                console.print(Panel(
                    "[bold yellow]Session interrupted. Goodbye! 👋[/bold yellow]",
                    border_style="yellow",
                    box=box.ROUNDED
                ))
                break
            except Exception as e:
                console.print(Panel(
                    f"[bold red]Error: {e}[/bold red]",
                    title="[bold red]❌ Error[/bold red]",
                    border_style="red",
                    box=box.ROUNDED
                ))
                console.print()
                query = await asyncio.to_thread(Prompt.ask, "[bold green]Enter your next query (or '/quit' to exit)[/bold green]")



if __name__ == '__main__':
    asyncio.run(main())
