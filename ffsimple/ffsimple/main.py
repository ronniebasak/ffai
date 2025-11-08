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
    'openrouter:openai/gpt-5-mini',
    # 'ollama:qwen3:8b',
    # 'Be concise, reply with one sentence.' is enough for some models (like openai) to use
    # the below tools appropriately, but others like anthropic and gemini require a bit more direction.
    instructions=
    dedent("""You are an video editor agent, your job is to look at the query and run
                If you think certain details are lacking, you can directly use the ask_user tool to ask questions to the user.
                Before asking the user questions such as which file etc, you can run ls -la using the shell or scan for video files to present which files they want converted
                Respond with SUCCESS only if the objective has been achieved, else use INDETERMINATE 
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


class LatLng(BaseModel):
    lat: float
    lng: float



async def main():
    # Get query from command-line arguments or prompt user
    if len(sys.argv) > 1:
        # Concatenate all arguments (excluding script name) as the query
        query = ' '.join(sys.argv[1:])
    else:
        # Prompt user for query
        query = input("Enter your query: ")
    
    async with AsyncClient() as client:
        logfire.instrument_httpx(client, capture_all=True, capture_request_body=True, capture_response_body=True)
        deps = Deps(client=client)
        result = await fforcagent.run(
            query, deps=deps
        )
        print('Response:', result.output.response)


if __name__ == '__main__':
    asyncio.run(main())
