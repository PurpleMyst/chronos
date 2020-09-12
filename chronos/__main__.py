import typing as t
import os

import discord
import structlog  # type: ignore

from .bot import Bot, Settings

settings = Settings()
client = discord.Client()
bot = Bot(client)


structlog.configure(
    processors=[
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.KeyValueRenderer(key_order=["event"]),
    ],
)


@client.event
async def on_message(message: discord.Message) -> None:
    await bot.on_message(message)


@client.event
async def on_reaction_add(
    reaction: discord.Reaction,
    user: t.Union[discord.User, discord.Member],
) -> None:
    await bot.on_reaction_add(reaction, user)


client.run(settings.discord_token)
