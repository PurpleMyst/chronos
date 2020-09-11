import typing as t
from datetime import datetime
import pickle
import os
from base64 import b64encode, b64decode
from functools import cached_property

import discord
import structlog  # type: ignore
import HumanTime as human_time  # type: ignore
import pydantic
from fuzzywuzzy.process import extractOne as fuzzy_find  # type: ignore

from .utils import utc, by_id


COMMAND_PREFIX = "c!"
HOF_EMOJI = "nat20"
HOF_COUNT = 4


class Storage(pydantic.BaseModel):
    parties: t.Dict[str, t.Dict[int, int]] = {}


class Bot:
    def __init__(self, client: discord.Client) -> None:
        self.client = client

        self._storage_msg: t.Optional[discord.Message] = None
        self._loaded_storage = False

        self._storage = Storage()

    @cached_property
    def _storage_channel(self) -> discord.TextChannel:
        guild: discord.Guild = by_id(
            int(os.environ["STORAGE_GUILD"]), self.client.guilds
        )
        return by_id(int(os.environ["STORAGE_CHANNEL"]), guild.text_channels)

    def _parse_identifier(
        self, in_message: discord.Message, ident: str
    ) -> int:
        "Convert an identifier (a name or an ID string) to an ID"

        # Try to parse the given identifier as a numeric ID
        try:
            return int(ident)
        except ValueError:
            pass

        # Try to match it to someone's display name in the current guild
        if in_message.guild is not None:
            members = {
                member.display_name: member.id
                for member in in_message.guild.members
            }
            member_id, _score, _key = fuzzy_find(ident, members)
            return t.cast(int, member_id)

        # If none of the previous checks succeeded, this identifier is (probably) invalid
        raise ValueError(f"Invalid identifier {ident!r}")

    async def _find_storage_message(self) -> bool:
        "Look for the storage message and return if it was found"
        if self._storage_msg is not None:
            return True

        # Search for the storage message in its channel's history
        async for msg in self._storage_channel.history():
            if msg.author == self.client.user:
                self._storage_msg = msg
                return True

        # If we get here, we didn't find anything
        return False

    async def _load_storage(self) -> None:
        logger = structlog.get_logger().bind()

        if await self._find_storage_message():
            logger.debug("load.found_storage")
            assert self._storage_msg is not None
            self._storage = Storage(
                **pickle.loads(b64decode(self._storage_msg.content))
            )
            logger.info("load.storage", storage=self._storage)
        else:
            logger.debug("load.no_storage")

    async def _save_storage(self) -> None:
        logger = structlog.get_logger().bind(storage=self._storage)

        content = b64encode(pickle.dumps(self._storage.dict())).decode("ascii")
        logger.debug("store.content", content=content)

        # If there's no storage message to be found, create it
        if not (await self._find_storage_message()):
            logger.info("store.created_message")
            self._storage_msg = await self._storage_channel.send(content)
            return

        logger.info("store.edited_message")
        assert self._storage_msg is not None
        await self._storage_msg.edit(content=content)

    async def _createparty(self, message: discord.Message) -> None:
        "Create a new party"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        partyname = message.content.split()[1]

        if partyname in self._storage.parties:
            logger.debug(
                "party.already_exists",
                party=partyname,
                parties=self._storage.parties,
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** already exists"
            )
            return

        self._storage.parties[partyname] = {}
        logger.info(
            "party.created", party=partyname, parties=self._storage.parties
        )
        await message.channel.send(
            f"<@{message.author.id}>: Created party **{partyname}**"
        )

    async def _deleteparty(self, message: discord.Message) -> None:
        "Delete an existing party"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        partyname = message.content.split()[1]

        if partyname in self._storage.parties:
            del self._storage.parties[partyname]
            logger.debug(
                "party.deleted", party=partyname, parties=self._storage.parties
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** was deleted"
            )
        else:
            logger.info(
                "party.unexisting",
                party=partyname,
                parties=self._storage.parties,
            )
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** does not exist"
            )

    async def _addtimezone(self, message: discord.Message) -> None:
        "Add yourself to a party, with your UTC offset"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        parts = message.content.split()
        if len(parts) != 3 and len(parts) != 4:
            await message.channel.send(
                f"<@{message.author.id}>: "
                "USAGE: !_addtimezone PARTY_NAME UTC_OFFSET [MEMBER_IDENTIFIER]"
            )
            return

        partyname = parts[1]
        offset = parts[2]

        if partyname not in self._storage.parties:
            await message.channel.send(
                f"<@{message.author.id}>: Party **{partyname}** does not exist"
            )
            return

        try:
            id_ = (
                self._parse_identifier(message, parts[3])
                if len(parts) == 4
                else message.author.id
            )
        except ValueError:
            await message.channel.send(
                f"<@{message.author.id}>: "
                "USAGE: !_addtimezone PARTY_NAME UTC_OFFSET [MEMBER_IDENTIFIER]"
            )
            return

        logger = logger.bind(party_member_id=id_)

        for partyname, party in self._storage.parties.items():
            if id_ in party:
                del party[id_]
                logger.info(
                    "party.removed",
                    party=partyname,
                    parties=self._storage.parties,
                )

        try:
            self._storage.parties[partyname][id_] = int(offset)
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
                parties=self._storage.parties,
            )

    def _party_of(self, user: int) -> t.Tuple[int, str, t.Dict[int, int]]:
        offset = None
        for partyname, party in self._storage.parties.items():
            if user in party:
                offset = party[user]
                return (offset, partyname, party)

        raise LookupError(f"Could not find party for user with ID {user}")

    async def _do_convert(
        self,
        channel: discord.TextChannel,
        party: t.Dict[int, int],
        dt: datetime,
    ) -> None:

        await channel.send(
            "\n".join(
                f"For <@{id_}>, in UTC{offset:+03}, "
                f"it's {dt.astimezone(utc(offset)).strftime('%A at %H:%M')}"
                for id_, offset in party.items()
            )
        )

    async def _convert(self, message: discord.Message) -> None:
        "Convert a given timestamp from your timezone to your party's timezones"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        try:
            _, time = message.content.split(" ", maxsplit=1)
        except ValueError:
            logger.debug("invalid_usage", content=message.content)
            await message.channel.send(
                f"<@{message.author.id}>: USAGE: c!_convert TIME"
            )
            return

        # Parse the time given by the message sender and
        # make sure it's not timezone-aware
        try:
            dt: datetime = human_time.parseTime(time)
        except ValueError:
            logger.debug("invalid_time", time=time)
            await message.channel.send(
                f"<@{message.author.id}>: Invalid timestamp {time!r}"
            )
            return

        assert dt.tzinfo is None
        logger.info("parsed_time", from_=time, to=dt)

        # Find the message sender's party and UTC offset
        try:
            offset, partyname, party = self._party_of(message.author.id)
        except LookupError:
            await message.channel.send(
                f"<@{message.author.id}>: You're not in any party!"
            )
            return
        logger.info("found_party", party=partyname, offset=offset)

        # Make the parsed datetime timezone-aware
        tz = utc(offset)
        dt = dt.replace(tzinfo=tz)

        # Calculate the correct datetime for each party member and show it
        assert isinstance(message.channel, discord.TextChannel)
        await self._do_convert(message.channel, party, dt)

    async def _convert_as(self, message: discord.Message) -> None:
        "Convert a given timestamp from someone's timezone to their party's timezones"

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        try:
            _, as_str, time = message.content.split(" ", maxsplit=2)
            as_ = self._parse_identifier(message, as_str)
        except ValueError:
            logger.debug("invalid_usage", content=message.content)
            await message.channel.send(
                f"<@{message.author.id}>: USAGE: c!_convert-as MEMBER_IDENTIFIER TIME"
            )
            return

        # Parse the time given by the message sender and
        # make sure it's not timezone-aware
        try:
            dt: datetime = human_time.parseTime(time)
        except ValueError:
            logger.debug("invalid_time", time=time)
            await message.channel.send(
                f"<@{message.author.id}>: Invalid timestamp {time!r}"
            )
            return
        assert dt.tzinfo is None
        logger.info("parsed_time", from_=time, to=dt)

        # Find the message sender's party and UTC offset
        try:
            offset, partyname, party = self._party_of(as_)
        except LookupError:
            await message.channel.send(
                f"<@{message.author.id}>: <@{as_}> is not in any party!"
            )
            return
        logger.info("found_party", as_=as_, party=partyname, offset=offset)

        # Make the parsed datetime timezone-aware
        tz = utc(offset)
        dt = dt.replace(tzinfo=tz)

        # Calculate the correct datetime for each party member and show it
        assert isinstance(message.channel, discord.TextChannel)
        await self._do_convert(message.channel, party, dt)

    async def _list_parties(self, message: discord.Message) -> None:
        "List the known parties"

        embed = discord.Embed(
            title="Parties",
            color=discord.Color.from_rgb(0x91, 0xD1, 0x8B),
        ).set_footer(
            text=f"{len(self._storage.parties)} found",
        )

        for partyname, party in self._storage.parties.items():
            embed.add_field(
                name=partyname,
                value=", ".join(
                    f"{self.client.get_user(id_)} (UTC{offset:+03})"
                    for id_, offset in party.items()
                ),
            )

        await message.channel.send(f"<@{message.author.id}>", embed=embed)

    async def _show_help(self, message: discord.Message) -> None:
        "Show the installed commands"

        embed = discord.Embed(
            title="Commands", color=discord.Color.from_rgb(0xE1, 0x1D, 0x74)
        )

        for command, func in self.COMMANDS.items():
            embed.add_field(
                name=f"!{command}", value=func.__doc__ or "No help given."
            )

        await message.channel.send(f"<@{message.author.id}>", embed=embed)

    async def _manual_hof(self, message: discord.Message) -> None:
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

        await self._add_to_hof(message)
        await message.channel.send(
            f"<@{message.author.id}>: Added message to the Hall of Fame"
        )

    async def _add_to_hof(self, message: discord.Message) -> None:
        author = message.author

        logger = structlog.get_logger().bind(
            message=message.id, author=message.author.id
        )
        logger.info("hof.add")

        hof_channel = self.client.get_channel(int(os.environ["HOF_CHANNEL"]))
        assert isinstance(hof_channel, discord.TextChannel)
        if hof_channel is None:
            logger.error("hof.notfound")
            return

        embed = (
            discord.Embed(url=message.jump_url, description=message.content)
            .set_author(name=author.name, icon_url=str(author.avatar_url))
            .set_footer(text=message.jump_url)
        )

        for embed in message.embeds:
            logger.debug("hof.embed.image", embed=embed, image=embed.image)
            if embed.image is not discord.Embed.Empty:  # type: ignore
                embed.set_image(url=embed.image.url)
                break

        await hof_channel.send(embed=embed)

    COMMANDS = {
        "create-party": _createparty,
        "delete-party": _deleteparty,
        "parties": _list_parties,
        "add-timezone": _addtimezone,
        "hof": _manual_hof,
        "convert": _convert,
        "convert-as": _convert_as,
        "help": _show_help,
    }

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.author == self.client.user:
            return

        if not message.content.startswith(COMMAND_PREFIX):
            return

        if not self._loaded_storage:
            await self._load_storage()
            self._loaded_storage = True

        logger = structlog.get_logger().bind(
            member_id=message.author.id, member_name=message.author.name
        )

        parts = message.content.split(" ", 1)
        command = parts[0][len(COMMAND_PREFIX) :]  # noqa
        logger.debug("command.requested", command=command)
        if command not in self.__class__.COMMANDS:
            logger.debug("command.notfound", command=command)
            return
        meth = self.__class__.COMMANDS[command]

        try:
            await meth(self, message)
        except Exception as e:
            logger.error("error", error=e)

        await self._save_storage()

    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        _user: t.Union[discord.User, discord.Member],
    ) -> None:
        logger = structlog.get_logger().bind(message_id=reaction.message.id)

        if (
            getattr(reaction.emoji, "name", reaction.emoji) != "nat20"
            or reaction.count != HOF_COUNT
        ):
            return

        logger.info("hof.reaction_reached")

        await self._add_to_hof(reaction.message)
