import discord  # type: ignore
import os

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


client.run(os.environ["DISCORD_TOKEN"])
