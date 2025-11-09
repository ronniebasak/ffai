"""Configuration management for FFSimple with Rich interactive UI."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import questionary
from platformdirs import user_config_dir
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box
from pick import pick

console = Console()

# Provider types
Provider = Literal["openrouter", "groq", "ollama"]

# Config directory
CONFIG_DIR = Path(user_config_dir("ffsimple", "ffai"))
CONFIG_FILE = CONFIG_DIR / "config.json"
CATALOG_REFRESH_DAYS = 1  # Check every 24 hours


class ConfigManager:
    """Manages configuration for FFSimple."""

    def __init__(self):
        self.config: dict[str, Any] = {}
        self.ensure_config_dir()

    def ensure_config_dir(self):
        """Create config directory if it doesn't exist."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def validate_openrouter_key(self, api_key: str) -> bool:
        """Validate OpenRouter API key format.
        
        Expected format: sk-or-v1- followed by 64 hexadecimal characters
        Example: sk-or-v1- xxxxxxxxxxxxxxxxxxxxxxxxxxxx
        """
        pattern = r'^sk-or-v1-[0-9a-fA-F]{64}$'
        return bool(re.match(pattern, api_key))

    def validate_groq_key(self, api_key: str) -> bool:
        """Validate Groq API key format.
        
        Expected format: gsk_ followed by alphanumeric characters (typically 48+ chars)
        Example: gsk_ XXXXXXXXXXXXXXX
        """
        pattern = r'^gsk_[a-zA-Z0-9]{40,}$'
        return bool(re.match(pattern, api_key))

    async def load_config(self) -> dict[str, Any]:
        """Load configuration from file or create new one."""
        if CONFIG_FILE.exists():
            try:
                 with open(CONFIG_FILE, "r") as f:
                    self.config = json.load(f)
                return self.config
            except (json.JSONDecodeError, IOError) as e:
                console.print(f"[bold red]Error loading config: {e}[/bold red]")
                console.print("[yellow]Starting fresh configuration...[/yellow]")
        
        # No config exists, run interactive setup
        return await self.interactive_setup()

    def save_config(self):
        """Save configuration to file."""
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
            console.print("[green]✓ Configuration saved successfully[/green]")
        except IOError as e:
            console.print(f"[bold red]Error saving config: {e}[/bold red]")

    async def interactive_setup(self) -> dict[str, Any]:
        """Interactive first-time setup with Rich UI."""
        # Display ASCII art banner
        from .ascii_art import display_ascii_banner
        display_ascii_banner(console)
        
        console.print()
        console.print(Panel.fit(
            "[bold cyan]🔧 FFSimple Configuration Setup[/bold cyan]\n"
            "Let's configure your AI provider and model.",
            border_style="cyan",
            box=box.DOUBLE
        ))
        console.print()

        # Select provider
        provider = await self.select_provider()
        
        # Get API key
        api_key = await self.prompt_for_api_key(provider)
        
        # Get Ollama base URL if using Ollama
        ollama_base_url = None
        if provider == "ollama":
            ollama_base_url = await self.prompt_for_ollama_base_url()
        
        # Fetch and select model
        model = await self.select_model(provider, api_key)
        
        # Build config
        self.config = {
            "provider": provider,
            "model": model,
            "last_used_model": f"{provider}:{model}",
            "api_keys": {
                "groq": api_key if provider == "groq" else None,
                "openrouter": api_key if provider == "openrouter" else None,
                "ollama": None
            },
            "ollama_base_url": ollama_base_url or "http://localhost:11434/v1",
            "model_catalogs": {},
            "catalog_last_updated": {}
        }
        
        self.save_config()
        
        console.print()
        console.print(Panel(
            f"[bold green]✓ Setup Complete![/bold green]\n\n"
            f"Provider: [cyan]{provider}[/cyan]\n"
            f"Model: [cyan]{model}[/cyan]",
            border_style="green",
            box=box.ROUNDED
        ))
        console.print()
        
        return self.config

    async def select_provider(self) -> Provider:
        """Interactive provider selection."""
        console.print(Panel(
            "[bold]Select your AI Provider:[/bold]\n\n"
            "Use arrow keys to navigate and Enter to select",
            title="[bold cyan]Provider Selection[/bold cyan]",
            border_style="cyan"
        ))
        console.print()
        
        choice = await questionary.select(
            "Select your AI Provider:",
            choices=[
                questionary.Choice("OpenRouter - Access to many models", value="openrouter"),
                questionary.Choice("Groq - Fast inference", value="groq"),
                questionary.Choice("Ollama - Local models", value="ollama")
            ],
            default="groq"
        ).ask_async()
        
        return choice

    async def prompt_for_ollama_base_url(self) -> str:
        """Prompt user for Ollama base URL with a helpful default."""
        console.print()
        console.print(Panel(
            "[bold cyan]🔗 Ollama Base URL Configuration[/bold cyan]\n\n"
            "For local Ollama installations, use the default URL.\n"
            "[dim]Only change this if you know what you're doing (e.g., remote Ollama server)[/dim]\n\n"
            "Default: [green]http://localhost:11434/v1[/green]",
            border_style="cyan"
        ))
        console.print()
        
        base_url = await asyncio.to_thread(
            Prompt.ask,
            "[bold cyan]Ollama Base URL[/bold cyan]",
            default="http://localhost:11434/v1"
        )
        
        console.print(f"[green]✓ Using Ollama base URL: {base_url}[/green]")
        return base_url

    async def prompt_for_api_key(self, provider: Provider) -> str | None:
        """Prompt user for API key with validation."""
        if provider == "ollama":
            console.print("[dim]Ollama doesn't require an API key (running locally)[/dim]")
            return None
        
        # Define expected formats
        format_info = {
            "openrouter": "sk-or-v1- followed by 64 hexadecimal characters\nExample: sk-or-v1- xxxxxxxxxxxxxxxxxxxx",
            "groq": "gsk_ followed by alphanumeric characters (typically 48+ chars)\nExample: gsk_ XXXXXXXXXXXXXXX"
        }
        
        console.print()
        console.print(Panel(
            f"[bold yellow]🔑 API Key Required[/bold yellow]\n\n"
            f"Enter your {provider.upper()} API key:\n\n"
            f"[dim]Expected format:[/dim]\n[dim]{format_info.get(provider, '')}[/dim]",
            border_style="yellow"
        ))
        
        # Validation loop
        max_attempts = 3
        for attempt in range(max_attempts):
            api_key = await asyncio.to_thread(
                Prompt.ask,
                f"[bold yellow]{provider.upper()} API Key[/bold yellow]",
                password=True
            )
            
            # Validate the API key
            is_valid = False
            if provider == "openrouter":
                is_valid = self.validate_openrouter_key(api_key)
            elif provider == "groq":
                is_valid = self.validate_groq_key(api_key)
            
            if is_valid:
                console.print("[green]✓ API key format is valid[/green]")
                return api_key
            else:
                console.print()
                console.print(f"[bold red]✗ Invalid API key format for {provider}[/bold red]")
                console.print(f"[yellow]Expected format: {format_info.get(provider, 'Unknown format')}[/yellow]")
                
                if attempt < max_attempts - 1:
                    console.print()
                    retry = await asyncio.to_thread(
                        Confirm.ask,
                        f"[yellow]Would you like to try again? ({max_attempts - attempt - 1} attempts remaining)[/yellow]",
                        default=True
                    )
                    if not retry:
                        console.print("[yellow]Proceeding with unvalidated key...[/yellow]")
                        return api_key
                    console.print()
                else:
                    console.print()
                    console.print("[yellow]⚠ Maximum attempts reached. Proceeding with unvalidated key...[/yellow]")
                    console.print("[dim]Note: The key may not work if the format is incorrect.[/dim]")
                    return api_key
        
        return api_key

    def fetch_groq_models(self, api_key: str) -> list[dict[str, Any]]:
        """Fetch available models from Groq API."""
        try:
            with console.status("[bold yellow]🔄 Fetching Groq models...[/bold yellow]"):
                response = httpx.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
        except httpx.HTTPError as e:
            console.print(f"[bold red]Error fetching Groq models: {e}[/bold red]")
            return []

    def fetch_openrouter_models(self) -> list[dict[str, Any]]:
        """Fetch available models from OpenRouter API (unauthenticated)."""
        try:
            with console.status("[bold yellow]🔄 Fetching OpenRouter models...[/bold yellow]"):
                response = httpx.get(
                    "https://openrouter.ai/api/v1/models",
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
        except httpx.HTTPError as e:
            console.print(f"[bold red]Error fetching OpenRouter models: {e}[/bold red]")
            return []

    def select_openrouter_hierarchical(self, models: list[dict[str, Any]]) -> str | None:
        """Select OpenRouter model with hierarchical provider/model selection.
        
        Returns:
            Model ID string, or None if user cancelled
        """
        # Group models by provider (split by '/')
        provider_groups: dict[str, list[dict[str, Any]]] = {}
        for model in models:
            model_id = model.get("id", "")
            if "/" in model_id:
                provider_name = model_id.split("/")[0]
                if provider_name not in provider_groups:
                    provider_groups[provider_name] = []
                provider_groups[provider_name].append(model)
        
        # Sort providers alphabetically
        sorted_providers = sorted(provider_groups.keys())
        
        console.print()
        console.print(Panel(
            "[bold cyan]OpenRouter Model Selection[/bold cyan]\n\n"
            "Step 1: Select Provider (use ↑↓ arrows, Enter to confirm)\n"
            "Step 2: Select Model (← Go Back option available)",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        # Navigation loop for back navigation support
        while True:
            # Step 1: Select provider
            provider_options = [f"{p} ({len(provider_groups[p])} models)" for p in sorted_providers]
            selected_provider_display, provider_index = pick(
                provider_options,
                "Select a provider:",
                indicator="→"
            )
            selected_provider = sorted_providers[provider_index]
            
            # Step 2: Select model from provider
            provider_models = provider_groups[selected_provider]
            
            # Add "Go Back" option at the beginning
            model_options = ["← Go Back to Provider Selection"]
            model_options.extend([
                f"{m.get('id', 'unknown')} (ctx: {m.get('context_length', 'N/A')})"
                for m in provider_models
            ])
            
            console.print()
            console.print(f"[bold green]✓ Selected provider: {selected_provider}[/bold green]")
            console.print()
            
            selected_model_display, model_index = pick(
                model_options,
                f"Select a model from {selected_provider}:",
                indicator="→"
            )
            
            # Check if user wants to go back
            if model_index == 0:  # "Go Back" was selected
                console.print()
                console.print("[yellow]← Going back to provider selection...[/yellow]")
                console.print()
                continue  # Loop back to provider selection
            
            # Adjust index since we added "Go Back" option
            actual_model_index = model_index - 1
            return provider_models[actual_model_index].get("id", "unknown")

    def select_groq_scrollable(self, models: list[dict[str, Any]]) -> str | None:
        """Select GROQ model with scrollable list.
        
        Returns:
            Model ID string, or None if user cancelled
        """
        console.print()
        console.print(Panel(
            "[bold cyan]GROQ Model Selection[/bold cyan]\n\n"
            "Use ↑↓ arrows to scroll through models, Enter to select",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        # Add "Cancel" option at the beginning
        model_options = ["← Cancel Selection"]
        model_options.extend([
            f"{m.get('id', 'unknown')} (ctx: {m.get('context_length', 'N/A')})"
            for m in models
        ])
        
        selected_model_display, model_index = pick(
            model_options,
            "Select a GROQ model:",
            indicator="→"
        )
        
        # Check if user wants to cancel
        if model_index == 0:  # "Cancel" was selected
            console.print()
            console.print("[yellow]Selection cancelled[/yellow]")
            return None
        
        # Adjust index since we added "Cancel" option
        actual_model_index = model_index - 1
        return models[actual_model_index].get("id", "unknown")

    async def select_model(self, provider: Provider, api_key: str | None) -> str:
        """Interactive model selection with retry support."""
        if provider == "ollama":
            console.print()
            console.print(Panel(
                "[bold]Ollama Model Configuration[/bold]\n\n"
                "Enter the model name and tag you want to use.\n"
                "Example: [cyan]llama3:8b[/cyan] or [cyan]qwen2.5:7b[/cyan]",
                border_style="cyan"
            ))
            model = await asyncio.to_thread(
                Prompt.ask,
                "[bold cyan]Model name[/bold cyan]",
                default="llama3:8b"
            )
            return model
        
        # Fetch models for groq/openrouter
        if provider == "groq":
            models = self.fetch_groq_models(api_key)
        else:  # openrouter
            models = self.fetch_openrouter_models()
        
        if not models:
            console.print("[bold red]No models available. Using default.[/bold red]")
            return "llama3-70b-8192" if provider == "groq" else "openai/gpt-3.5-turbo"
        
        # Cache the catalog
        self.config["model_catalogs"] = self.config.get("model_catalogs", {})
        self.config["model_catalogs"][provider] = models
        self.config["catalog_last_updated"] = self.config.get("catalog_last_updated", {})
        self.config["catalog_last_updated"][provider] = datetime.now().isoformat()
        
        # Retry loop in case user cancels and wants to try again
        while True:
            # Use hierarchical selection for OpenRouter, scrollable for GROQ
            if provider == "openrouter":
                selected_model = await asyncio.to_thread(
                    self.select_openrouter_hierarchical,
                    models
                )
            else:  # groq
                selected_model = await asyncio.to_thread(
                    self.select_groq_scrollable,
                    models
                )
            
            # If user cancelled (returned None), ask if they want to try again
            if selected_model is None:
                console.print()
                retry = await asyncio.to_thread(
                    Confirm.ask,
                    "[yellow]No model selected. Try again?[/yellow]",
                    default=True
                )
                if not retry:
                    # User doesn't want to retry, use default
                    console.print("[yellow]Using default model...[/yellow]")
                    return "llama3-70b-8192" if provider == "groq" else "openai/gpt-3.5-turbo"
                # Otherwise, loop continues and prompts again
                continue
            
            # Valid selection made
            console.print()
            console.print(f"[bold green]✓ Selected model: {selected_model}[/bold green]")
            console.print()
            
            return selected_model

    def refresh_model_catalog(self, provider: Provider, force: bool = False):
        """Refresh model catalog if needed."""
        if not force:
            last_updated = self.config.get("catalog_last_updated", {}).get(provider)
            if last_updated:
                last_date = datetime.fromisoformat(last_updated)
                if datetime.now() - last_date < timedelta(days=CATALOG_REFRESH_DAYS):
                    return  # Still fresh
        
        console.print(f"[yellow]Refreshing {provider} model catalog...[/yellow]")
        
        if provider == "groq":
            api_key = self.config["api_keys"].get("groq")
            if api_key:
                models = self.fetch_groq_models(api_key)
                if models:
                    self.config["model_catalogs"][provider] = models
                    self.config["catalog_last_updated"][provider] = datetime.now().isoformat()
                    self.save_config()
        elif provider == "openrouter":
            models = self.fetch_openrouter_models()
            if models:
                self.config["model_catalogs"][provider] = models
                self.config["catalog_last_updated"][provider] = datetime.now().isoformat()
                self.save_config()

    async def interactive_config_menu(self):
        """Interactive configuration update menu."""
        console.print()
        console.print(Panel(
            f"[bold]Current Configuration[/bold]\n\n"
            f"Provider: [cyan]{self.config.get('provider', 'N/A')}[/cyan]\n"
            f"Model: [cyan]{self.config.get('model', 'N/A')}[/cyan]\n"
            f"Last Updated: [cyan]{self.config.get('catalog_last_updated', {}).get(self.config.get('provider', ''), 'Never')}[/cyan]",
            title="[bold cyan]⚙️  Configuration[/bold cyan]",
            border_style="cyan"
        ))
        console.print()
        console.print("[dim]Use arrow keys to navigate and Enter to select[/dim]")
        console.print()
        
        choice = await questionary.select(
            "What would you like to update?",
            choices=[
                questionary.Choice("Change provider", value="1"),
                questionary.Choice("Change model", value="2"),
                questionary.Choice("Update API keys", value="3"),
                questionary.Choice("Refresh model catalog", value="4"),
                questionary.Choice("Exit", value="5")
            ],
            default="5"
        ).ask_async()
        
        if choice == "1":
            provider = await self.select_provider()
            
            # Check if API key already exists for this provider
            existing_api_key = self.config.get("api_keys", {}).get(provider)
            
            if existing_api_key:
                console.print(f"[green]✓ Using existing API key for {provider}[/green]")
                api_key = existing_api_key
            else:
                api_key = await self.prompt_for_api_key(provider)
            
            model = await self.select_model(provider, api_key)
            self.config["provider"] = provider
            self.config["model"] = model
            self.config["last_used_model"] = f"{provider}:{model}"
            if api_key:
                self.config["api_keys"][provider] = api_key
            self.save_config()
        elif choice == "2":
            provider = self.config.get("provider")
            api_key = self.config["api_keys"].get(provider)
            model = await self.select_model(provider, api_key)
            self.config["model"] = model
            self.config["last_used_model"] = f"{provider}:{model}"
            self.save_config()
        elif choice == "3":
            provider = self.config.get("provider")
            api_key = await self.prompt_for_api_key(provider)
            if api_key:
                self.config["api_keys"][provider] = api_key
                self.save_config()
        elif choice == "4":
            provider = self.config.get("provider")
            self.refresh_model_catalog(provider, force=True)
        else:
            console.print("[dim]No changes made.[/dim]")

    def get_model_config(self, provider_override: str | None = None, model_override: str | None = None) -> tuple[str, str, str | None, str | None]:
        """Get model configuration with optional overrides.
        
        Returns:
            Tuple of (provider, model, api_key, ollama_base_url)
        """
        provider = provider_override or self.config.get("provider", "groq")
        model = model_override or self.config.get("model", "llama3-70b-8192")
        api_key = self.config.get("api_keys", {}).get(provider)
        ollama_base_url = self.config.get("ollama_base_url", "http://localhost:11434/v1")
        
        # Update last used if different
        current_combo = f"{provider}:{model}"
        if current_combo != self.config.get("last_used_model"):
            self.config["last_used_model"] = current_combo
            self.save_config()
        
        return provider, model, api_key, ollama_base_url


async def load_config() -> ConfigManager:
    """Load or create configuration."""
    manager = ConfigManager()
    await manager.load_config()
    return manager
