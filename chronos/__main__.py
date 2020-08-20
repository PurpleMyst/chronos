import discord

from . import secretdata
from .bot import Bot

client = discord.Client()
bot = Bot(client)


@client.event
async def on_ready():
    await bot.on_ready()


@client.event
async def on_message(message):
    # Don't wanna answer to bots (including ourselves)
    if message.author.bot or message.author == client.user:
        return

    await bot.on_message(message)


client.run(secretdata.TOKEN)
