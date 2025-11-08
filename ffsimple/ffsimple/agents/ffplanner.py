"""Example of Pydantic AI with multiple tools which the LLM needs to call in turn to answer a question.

In this case the idea is a "weather" agent — the user can ask for the weather in multiple cities,
the agent will use the `get_lat_lng` tool to get the latitude and longitude of the locations, then use
the `get_weather` tool to get the weather.

Run with:

    uv run -m pydantic_ai_examples.weather_agent
"""

from __future__ import annotations as _annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import logfire
from httpx import AsyncClient
from pydantic import BaseModel

from pydantic_ai import Agent, RunContext
from dotenv import load_dotenv
from textwrap import dedent
load_dotenv()

# 'if-token-present' means nothing will be sent (and the example will work) if you don't have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()


@dataclass
class Deps:
    client: AsyncClient


fforcagent = Agent(
    # 'openrouter:moonshotai',
    'ollama:qwen3:8b',
    # 'Be concise, reply with one sentence.' is enough for some models (like openai) to use
    # the below tools appropriately, but others like anthropic and gemini require a bit more direction.
    instructions=
    dedent("""You are a planner agent, you have access to many tools"""),
    deps_type=Deps,
    retries=2,
)










@fforcagent.tool
async def planner_agent(ctx: RunContext[Deps]):
    """
    """
    ...


class LatLng(BaseModel):
    lat: float
    lng: float



async def main():
    async with AsyncClient() as client:
        logfire.instrument_httpx(client, capture_all=True, capture_request_body=True, capture_response_body=True)
        deps = Deps(client=client)
        result = await fforcagent.run(
            'Convert this file to 720p', deps=deps
        )
        print('Response:', result.output)


if __name__ == '__main__':
    asyncio.run(main())