import typing as t
from datetime import datetime, timezone, timedelta
import pickle
from base64 import b64encode, b64decode

import discord  # type: ignore
import structlog  # type: ignore
import HumanTime as human_time  # type: ignore

from . import secretdata


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

    def _storage_channel(self) -> discord.TextChannel:
        guild: discord.Guild = by_id(secretdata.GUILD, self.client.guilds)
        return by_id(secretdata.STORAGE_CHANNEL, guild.text_channels)

    async def _find_storage_message(self) -> bool:
        "Look for the storage message and return if it was found"
        if self.storage_msg is not None:
            return True

        # Search for the storage message in its channel's history
        async for msg in self._storage_channel().history():
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
            self.storage_msg = await self._storage_channel().send(content)
            return

        assert self.storage_msg is not None
        await self.storage_msg.edit(content=content)

    async def on_ready(self) -> None:
        logger = structlog.get_logger()
        await self.load_parties()
        logger.info("ready", parties=self.parties)

    async def createparty(self, message: discord.Message) -> None:
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
            if message.author.id in party.items():
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

    async def on_message(self, message: discord.Message) -> None:
        if message.content.startswith("!createparty "):
            await self.createparty(message)
        elif message.content.startswith("!addtimezone "):
            await self.addtimezone(message)
        elif message.content.startswith("!convert "):
            await self.convert(message)

        await self.store_parties()
