# chronos

`chronos` is a Discord bot that manages timezones for DND parties, or any kind of group.  
It also does an "Hall of Fame" for messages, for unrelated reasons :p

## Setup

### Self-Host

Making sure you've got at least Python 3.8, run the following in the repository directory:

```shell
$ python3 -m pip install --user -r requirements.txt
$ python3 -m pip install --user -e .
```

Now, you must create a bot application in the Discord developer portal,
[here's an guide from discord.js](https://discordjs.guide/preparations/setting-up-a-bot-application.html).

Then, you must set up your environment with the following environment variables:

- `DISCORD_TOKEN`: Your discord bot token.
- `STORAGE_CHANNEL`: The ID of the channel that will be used for storage (see below for details)

Now, you can just run the `chronos` python package and add your self-hosted bot to servers:

```shell
$ python3 -m chronos
```

### Already-Existing

Create a GitHub issue requesting the addition of the bot to your server and I will consider adding it.

## Functionality

### Parties

Parties are the main functionality of the bot, and their usage is as follows:

1. Party creation/deletion is handled through `c!create-party` and `c!delete-party`.  
   Just pass the (case-sensitive) name of the party as an argument, but note it must be a single word (No spaces!)
2. To add a member to a party, you must use `c!add-timezone`  
   Pass in order the party name, the UTC offset of the new member, and either the ID or (part of) the display name of the member. If you don't pass an ID/name, you will be added to the party. You can only be in one party at a time, though.
3. To convert between timezones, you can either use `c!convert` or `c!convert-as`  
   `c!convert` just treats everything following the command as a timestamp,
   meanwhile `c!convert-as` treats the first word after the command as the identifier of the user to take into consideration
4. `c!parties` lists all known parties.

### Hall of Fame

To configure the hall of fame, you must use `c!configure-hof` with the reaction emoji's name, the reaction count and the hall-of-fame channel ID.

Any messages that gets more than N reacts with the chosen emote will be added to the HoF channel.
You can also use `c!hof` with a message ID to manually add a message to the hall of fame.

## Storage

Due to the usefulness of this bot being based on the data it can store, it needed some sort of storage container.  
Due to the fact that I wanted to leverage existing storage and avoid paying if possible, I chose to implement the following:

1. The bot's data is kept as a `pydantic` model: this ensures data integrity,
   by validating and converting the data to and from any format I chose to marshal it in.
2. The data is converted to and from a base64-encoded pickle payload: this ensures I can marshal
   any value Python supports and have it in a known, safe, ASCII subset.
3. The data is kept in a Discord message in a designated storage channel: this ensures that the data will _always_
   be available and in a place that does not cost extra.

All in all, this solution does, at least at the moment, everything I need it to do.  
In the future, I may have to expand this solution to support splitting the data over multiple messages,
as a single message has a size limit.
