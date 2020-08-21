import typing as t
import os

import discord  # type: ignore

from .bot import Bot

client = discord.Client()
bot = Bot(client)


@client.event
async def on_ready() -> None:
    await bot.on_ready()


@client.event
async def on_message(message: discord.Message) -> None:
    # Don't wanna answer to bots (including ourselves)
    if message.author.bot or message.author == client.user:
        return

    await bot.on_message(message)


@client.event
async def on_reaction_add(
    reaction: discord.Reaction, user: t.Union[discord.User, discord.Member],
) -> None:
    await bot.on_reaction_add(reaction, user)


client.run(os.environ["DISCORD_TOKEN"])
