import typing as t
from datetime import datetime, timezone, timedelta
import pickle
import os
from base64 import b64encode, b64decode
from functools import cached_property

import discord  # type: ignore
import structlog  # type: ignore
import HumanTime as human_time  # type: ignore


COMMAND_PREFIX = "c!"
HOF_EMOJI = "nat20"
HOF_COUNT = 4


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
        logger = structlog.get_logger.bind()

        if await self._find_storage_message():
            logger.debug("load.found_storage", parties=self.parties)
            assert self.storage_msg is not None
            self.parties = pickle.loads(b64decode(self.storage_msg.content))
            logger.info("load.parties", parties=self.parties)
        else:
            logger.debug("load.no_storage", parties=self.parties)

    async def store_parties(self) -> None:
        logger = structlog.get_logger.bind()

        content = b64encode(pickle.dumps(self.parties)).decode("ascii")
        logger.debug("store.content", content=content)

        # If there's no storage message to be found, create it
        if not (await self._find_storage_message()):
            logger.info("store.created_message", parties=self.parties)
            self.storage_msg = await self._storage_channel.send(content)
            return

        logger.info("store.edited_message", parties=self.parties)
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

        if partyname in self.parties:
            logger.debug(
                "party.already_exists", party=partyname, parties=self.parties
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** already exists"
            )
            return

        self.parties[partyname] = {}
        logger.info("party.created", party=partyname, parties=self.parties)
        await message.channel.send(
            f"<@{message.author.id}>: Created party **{partyname}**"
        )

    async def deleteparty(self, message: discord.Message) -> None:
        "Delete an existing party"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        partyname = message.content.split()[1]

        if partyname in self.parties:
            del self.parties[partyname]
            logger.debug(
                "party.deleted", party=partyname, parties=self.parties
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** was deleted"
            )
        else:
            logger.info(
                "party.unexisting", party=partyname, parties=self.parties
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** does not exist"
            )

    async def addtimezone(self, message: discord.Message) -> None:
        "Add yourself to a party, with your UTC offset"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        parts = message.content.split()
        if len(parts) != 3 or len(parts) != 4:
            await message.channel.send(
                f"<@{message.author.id}>: "
                "USAGE: !addtimezone PARTY_NAME UTC_OFFSET [MEMBER_ID]"
            )
            return

        partyname = parts[1]
        offset = parts[2]

        if partyname not in self.parties:
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** does not exist"
            )
            return

        id_ = parts[3] if len(parts) == 4 else message.author.id
        logger = logger.bind(party_member_id=id_)

        for partyname, party in self.parties.items():
            if id_ in party:
                del party[id_]
                logger.info(
                    "party.removed", party=partyname, parties=self.parties
                )

        try:
            self.parties[partyname][id_] = int(offset)
        except ValueError:
            await message.channel.send(
                f"<@{message.author.id}>: Invalid offset {offset}"
            )
        else:
            await message.channel.send(f"Added <@{id_}> to **{partyname}**")
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
            title="Parties", color=discord.Color.from_rgb(0x91, 0xD1, 0x8B),
        ).set_footer(text=f"{len(self.parties)} found",)

        for partyname, party in self.parties.items():
            embed.add_field(
                name=partyname,
                value=", ".join(
                    f"{self.client.get_user(id_)} (UTC{offset:+03})"
                    for id_, offset in party.items()
                ),
            )

        await message.channel.send(f"<@{message.author.id}>", embed=embed)

    async def show_help(self, message: discord.Message) -> None:
        "Show the installed commands"

        embed = discord.Embed(
            title="Commands", color=discord.Color.from_rgb(0xE1, 0x1D, 0x74)
        )

        for command, func in self.COMMANDS.items():
            embed.add_field(
                name=f"!{command}", value=func.__doc__ or "No help given."
            )

        await message.channel.send(f"<@{message.author.id}>", embed=embed)

    async def manual_hof(self, message: discord.Message) -> None:
        "Manually add a message to the HOF"

        parts = message.content.split()
        if len(parts) != 2:
            await message.channel.send(
                f"<@{message.author.id}>: USAGE: !hof MESSAGE_ID"
            )
            return

        try:
            message_id = int(parts[1])
        except ValueError:
            await message.channel.send(
                f"<@{message.author.id}>: USAGE: !hof MESSAGE_ID"
            )
            return

        try:
            message = await message.channel.fetch_message(message_id)
        except discord.NotFound:
            await message.channel.send(
                f"<@{message.author.id}>: Message not found."
            )
            return

        await self.add_to_hof(message)
        await message.channel.send(
            f"<@{message.author.id}>: Added message to the Hall of Fame"
        )

    async def add_to_hof(self, message: discord.Message) -> None:
        author = message.author

        logger = structlog.get_logger().bind(
            message=message.id, author=message.author.id
        )
        logger.info("hof.add")

        hof_channel = self.client.get_channel(int(os.environ["HOF_CHANNEL"]))
        if hof_channel is None:
            logger.error("hof.notfound")
            return

        embed = (
            discord.Embed(url=message.jump_url, description=message.content)
            .set_author(name=author.name, icon_url=str(author.avatar_url))
            .set_footer(text=message.jump_url)
        )

        for embed in message.embeds:
            if embed.image is not discord.Embed.Empty:
                embed.set_image(embed.image.url)
                break

        await hof_channel.send(embed=embed)

    COMMANDS = {
        "createparty": createparty,
        "deleteparty": deleteparty,
        "parties": list_parties,
        "addtimezone": addtimezone,
        "hof": manual_hof,
        "convert": convert,
        "help": show_help,
    }

    async def on_message(self, message: discord.Message) -> None:
        if not message.content.startswith(COMMAND_PREFIX):
            return

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        command = message.content.split(" ", 1)[0][len(COMMAND_PREFIX) :]
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

    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        _user: t.Union[discord.User, discord.Member],
    ) -> None:
        if (
            getattr(reaction.emoji, "name", reaction.emoji) != "nat20"
            or reaction.count != HOF_COUNT
        ):
            return

        await self.add_to_hof(reaction.message)

