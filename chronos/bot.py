import typing as t
from datetime import datetime, timezone, timedelta
import pickle
import os
from base64 import b64encode, b64decode
from functools import cached_property

import discord  # type: ignore
import structlog  # type: ignore
import HumanTime as human_time  # type: ignore


def utc(offset: int) -> timezone:
    return timezone(timedelta(hours=offset))


def by_id(needle_id: int, haystack: t.Iterable[t.Any]) -> t.Any:
    "Find an item by its ID in an iterable"
    return next(item for item in haystack if item.id == needle_id)


class Bot:
    def __init__(self, client: discord.Client) -> None:
        self.client = client

        self.storage_msg: t.Optional[discord.Message] = None
        self.parties: t.Dict[str, t.Dict[int, int]] = {}

    @cached_property
    def _storage_channel(self) -> discord.TextChannel:
        guild: discord.Guild = by_id(
            int(os.environ["STORAGE_GUILD"]), self.client.guilds
        )
        return by_id(int(os.environ["STORAGE_CHANNEL"]), guild.text_channels)

    async def _find_storage_message(self) -> bool:
        "Look for the storage message and return if it was found"
        if self.storage_msg is not None:
            return True

        # Search for the storage message in its channel's history
        async for msg in self._storage_channel.history():
            if msg.author == self.client.user:
                self.storage_msg = msg
                return True

        # If we get here, we didn't find anything
        return False

    async def load_parties(self) -> None:
        if await self._find_storage_message():
            assert self.storage_msg is not None
            self.parties = pickle.loads(b64decode(self.storage_msg.content))

    async def store_parties(self) -> None:
        content = b64encode(pickle.dumps(self.parties)).decode("ascii")

        # If there's no storage message to be found, create it
        if not (await self._find_storage_message()):
            self.storage_msg = await self._storage_channel.send(content)
            return

        assert self.storage_msg is not None
        await self.storage_msg.edit(content=content)

    async def on_ready(self) -> None:
        logger = structlog.get_logger().bind()
        await self.load_parties()
        logger.info("ready", parties=self.parties)

    async def createparty(self, message: discord.Message) -> None:
        "Create a new party"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        partyname = message.content.split()[1]
        self.parties[partyname] = {}
        logger.info("party.created", party=partyname, parties=self.parties)
        await message.channel.send(
            f"<@{message.author.id}>: Created party **{partyname}**"
        )

    async def addtimezone(self, message: discord.Message) -> None:
        "Add yourself to a party, with your UTC offset"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        parts = message.content.split()
        if len(parts) != 3:
            await message.channel.send(
                f"<@{message.author.id}>: "
                "USAGE: !addtimezone PARTY_NAME UTC_OFFSET"
            )
            return

        _, partyname, offset = parts

        if partyname not in self.parties:
            await message.channel.send(
                f"<@{message.author.id}>: Party {partyname!r} does not exist"
            )
            return

        for partyname, party in self.parties.items():
            if message.author.id in party:
                del party[message.author.id]
                logger.info(
                    "party.removed", party=partyname, parties=self.parties
                )

        try:
            self.parties[partyname][message.author.id] = int(offset)
        except ValueError:
            await message.channel.send(
                f"<@{message.author.id}>: Invalid offset {offset}"
            )
        else:
            await message.channel.send(
                f"Added <@{message.author.id}> to {partyname!r}"
            )
            logger.info(
                "party.added",
                party=partyname,
                utc_offset=int(offset),
                parties=self.parties,
            )

    async def convert(self, message: discord.Message) -> None:
        "Convert a given timestamp to your party's timezones"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        # Parse the time given by the message sender and
        # make sure it's not timezone-aware
        _, time = message.content.split(" ", maxsplit=1)
        dt: datetime = human_time.parseTime(time)
        assert dt.tzinfo is None
        logger.info("parsed_time", from_=time, to=dt)

        # Find the message sender's party and UTC offset
        offset = None
        for partyname, party in self.parties.items():
            if message.author.id in party:
                offset = party[message.author.id]
                break
        else:  # no break
            await message.channel.send(
                f"<@{message.author.id}>: You're not in any party!"
            )
            return
        logger.info("found_party", party=partyname, offset=offset)

        # Make the parsed datetime timezone-aware
        tz = utc(offset)
        dt = dt.replace(tzinfo=tz)

        # Calculate the correct datetime for each party member and show it
        await message.channel.send(
            "\n".join(
                f"For <@{id_}>, in UTC{offset:+03}, "
                f"it's {dt.astimezone(utc(offset)).strftime('%A at %H:%M')}"
                for id_, offset in party.items()
            )
        )

    async def list_parties(self, message: discord.Message) -> None:
        "List the known parties"

        embed = discord.Embed(
            title="Parties", color=discord.Color.from_rgb(0x2A, 0x17, 0x42)
        )

        for partyname, party in self.parties.items():
            embed.add_field(
                name=partyname,
                value=", ".join(
                    f"{self.client.get_user(id_)} (UTC{offset:+03})"
                    for id_, offset in party.items()
                ),
            )

        await message.channel.send(embed=embed)

    async def show_help(self, message: discord.Message) -> None:
        "Show the installed commands"

        embed = discord.Embed(
            title="Parties", color=discord.Color.from_rgb(0x2A, 0x17, 0x42)
        )

        for command, func in self.COMMANDS.items():
            embed.add_field(
                name=f"!{command}", value=func.__doc__ or "No help given."
            )

        await message.channel.send(embed=embed)

    COMMANDS = {
        "createparty": createparty,
        "parties": list_parties,
        "addtimezone": addtimezone,
        "convert": convert,
        "help": show_help,
    }

    async def on_message(self, message: discord.Message) -> None:
        if not message.content.startswith("!"):
            return

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        command = message.content.split(" ", 1)[0][1:]
        logger.debug("command.requested", command=command)
        if command not in self.__class__.COMMANDS:
            logger.debug("command.notfound", command=command)
            return
        meth = self.__class__.COMMANDS[command]

        try:
            await meth(self, message)
        except Exception as e:
            logger.error("error", error=e)

        await self.store_parties()
