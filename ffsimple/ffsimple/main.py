"""Example of Pydantic AI with multiple tools which the LLM needs to call in turn to answer a question.

In this case the idea is a "weather" agent — the user can ask for the weather in multiple cities,
the agent will use the `get_lat_lng` tool to get the latitude and longitude of the locations, then use
the `get_weather` tool to get the weather.

Run with:

    uv run -m pydantic_ai_examples.weather_agent
"""

from __future__ import annotations as _annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Any

import logfire


class QuitChatException(Exception):
    """Exception raised when the quit_chat tool is called."""
    pass


from httpx import AsyncClient
from pydantic import BaseModel

from pydantic_ai import Agent, RunContext
from dotenv import load_dotenv
from textwrap import dedent
from enum import Enum
from .tools.secure_shell import execute_shell
from .deps.deps import Deps
load_dotenv()

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


fforcagent = Agent(
    # 'openrouter:openai/gpt-5-mini',
    # 'ollama:qwen3:8b',
    # 'openrouter:moonshotai/kimi-k2-0905',
    # 'openrouter:openai/gpt-oss-20b',
    'groq:moonshotai/kimi-k2-instruct-0905',
    # 'Be concise, reply with one sentence.' is enough for some models (like openai) to use
    # the below tools appropriately, but others like anthropic and gemini require a bit more direction.
    instructions=
    dedent("""You are an video editor agent, your job is to look at the query and run
                If you think certain details are lacking, you can directly use the ask_user tool to ask questions to the user.
                Before asking the user questions such as which file etc, you can run ls -la using the shell or scan for video files to present which files they want converted
                Respond with SUCCESS only if the objective has been achieved, else return INDETERMINATE
           
                NOTE: in shell scripts, we need to escape/quote parameters that has spaces in them
                Always Verify your results by running ls/find and ffprobe to ensure the desired output has been achieved
           
                if we detect any incompatibilities (such as resolution, framerate etc) present user with options such as letterboxing, 60fps vs 30fps, try and pick best option beforehand
                only if the user confirms, you can use the executor agent"""),
    output_type=OrcResponse,
    deps_type=Deps,
    retries=2,
)



@fforcagent.tool
async def ask_user(ctx: RunContext[Deps], prompt: str) -> str:
    """Takes a prompt, asks clarification from the user and returns it. You should use this tool to show info to the user, do not return until objective is achieved"""
    a = input(prompt + "\n > ")
    return a

fforcagent.tool(execute_shell)


@fforcagent.tool
async def tell_user(ctx: RunContext[Deps], prompt: str) -> str:
    """Takes a prompt and displays it to the user in a nice and friendly way"""
    a = input(prompt + "\n > ")
    return "Continue your execution"


@fforcagent.tool
async def quit_chat(ctx: RunContext[Deps], reason: str = "") -> str:
    """End the conversation. Use this when the user wants to exit or the task is fully complete."""
    raise QuitChatException(reason)

@fforcagent.system_prompt
async def get_current_dir(ctx: RunContext[Deps]):
    lsla = execute_shell(ctx,"ls -la").stdout
    unamea = execute_shell(ctx, "uname -a").stdout
    date = execute_shell(ctx, "date").stdout
    return f"\n---\nCurrent directory contents:\n{lsla}\n\n---\nUname -a\n{unamea}\n\n---\nDate Time info\n\n{date}\n"


class LatLng(BaseModel):
    lat: float
    lng: float



async def main():
    # Get initial query from command-line arguments or prompt user
    if len(sys.argv) > 1:
        # Concatenate all arguments (excluding script name) as the query
        query = ' '.join(sys.argv[1:])
    else:
        # Prompt user for query
        query = input("Enter your query: ")
    
    async with AsyncClient() as client:
        logfire.instrument_httpx(client, capture_all=True)
        deps = Deps(client=client)
        
        # Initialize message history to maintain context across follow-up queries
        message_history = None
        
        # Continuous conversation loop
        while True:
            try:
                # Check if user wants to quit
                if query.strip().lower() == '/quit':
                    print("Goodbye!")
                    break
                
                # Run the agent with the current query, preserving message history
                result = await fforcagent.run(query, deps=deps, message_history=message_history)
                print('Response:', result.output.response)
                
                # Store message history for next iteration to maintain context
                message_history = result.all_messages()
                
                # Prompt for next query
                print("\n" + "="*50)
                query = input("Enter your next query (or '/quit' to exit): ")
                
            except QuitChatException as e:
                # quit_chat tool was called - exit immediately
                reason = str(e) if str(e) else "User requested exit"
                print(f"\nGoodbye! {reason}")
                break
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
                query = input("\nEnter your next query (or '/quit' to exit): ")


if __name__ == '__main__':
    asyncio.run(main())
