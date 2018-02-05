import re
import discord
import io
import logging
import time

from bs4 import BeautifulSoup
from functools import wraps
from discord.ext.commands.bot import _get_variable

from .config import Config, ConfigDefaults, load_json, dump_json
from .exceptions import BotException, InvalidUsage, PermissionsError, HelpfulError, HelpfulWarning, Signal, RestartSignal, TerminateSignal
from .database import Database
from .deets import BACKUP_TAGS

log = logging.getLogger(__name__)


class Response:
    """
    Response class for commands and deletes replied message after x-time
    """

    def __init__(self, content, reply=True, delete=0):
        self.content = content
        self.reply = reply
        self.delete = delete


class Commands:
    """
    All commands for the bot will reside here
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.db = bot.db
        self.req = bot.req
        self.owner = self.config.owner

    def owner_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Only allow the owner to use these commands
            message = _get_variable('message')

            if not message or message.author.id == self.config.owner.id:
                # noinspection PyCallingNonCallable
                return await func(self, *args, **kwargs)
            else:
                raise PermissionsError(":warning: Only the owner can use this command.", delete=10)
        return wrapper

    def requires_db(func):
        """
        Requires a database connection
        """
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            message = _get_variable('message')

            if not message or self.db.db is not None:
                return await func(self, *args, **kwargs)
            else:
                return Response(":warning: This command cannot be used. Only read-only commands can be used while the database is unavailable", delete=10)

        return wrapper

##########################################################################
#                    Misc(latency commands and others)
##########################################################################

    async def c_ping(self, author):
        """
        Usage: {prefix}ping
        Replies with "Pong!"; Used to test bot's latency.
        """
        return Response(':ping_pong:{}, Pong!!'.format(author.mention), delete=60)

    async def c_marco(self, author):
        """
        Usage: {prefix}marco
        Replies with "Polo!"; Used to test bot's latency.
        """
        return Response(':water_polo:{}, Polo!!'.format(author.mention), delete=60)

##########################################################################
#                             User-Info
##########################################################################

    @staticmethod
    def _getRoles(roles):
        string = ''
        for r in roles:
            if not r.is_everyone:
                string += '{}, '.format(r.name)
        if string is '':
            return 'None'
        else:
            return string[:-2]

    async def c_id(self, author, user_mentions):
        """
        Usage: {prefix}id <@user>
        Tells the user their id or the id of another user.
        """
        if not user_mentions:
            return Response('{}, your id is `{}`'.format(author.mention, author.id), reply=True, delete=10)
        else:
            usr = user_mentions[0]
            return Response("{}'s id is `{}`".format(usr.name, usr.id), reply=True, delete=10)

    async def c_info(self, server, author, user_mentions):
        """
        Usage: {prefix}info <@user>
        Provides info on a user mentiontion, if no user mentioned returns no_entry
        """
        if user_mentions:
            usr = user_mentions[0]
            embed = discord.Embed()
            embed.colour = 0xfeb23d
            embed.set_author(name='{} AKA {}'.format(usr, usr.display_name), icon_url=usr.avatar_url)
            embed.set_thumbnail(url=usr.avatar_url)
            embed.add_field(name='({})'.format(usr.id), value='No other names')
            embed.add_field(name='Created:', value='{}'.format(usr.created_at))
            embed.add_field(name='Joined:', value='{}'.format(usr.joined_at))
            embed.add_field(name='Roles:', value='{}'.format(self._getRoles(usr.roles)))
            embed.set_footer(text='{} | {}'.format(server.region, time.strftime("%a %b %D, %Y at %I:%M %p")))
        else:
            embed = discord.Embed()
            embed.colour = 0xfeb23d
            if server == 'Gearheads and Gamers':
                embed.set_author(name=server, url=str('https://gearheadsandgamers.com'), icon_url=server.icon_url)
            else:
                embed.set_author(name=server, icon_url=server.icon_url)
            embed.set_thumbnail(url=server.icon_url)
            embed.add_field(name=server.id, value='{} / {} Members'.format(len([m for m in server.members if not m.status == discord.Status.offline]), server.member_count))
            embed.add_field(name='Owner:', value='{} ({})'.format(server.owner, server.owner.id))
            embed.add_field(name='Roles:', value="This server has {} roles".format(len(list(server.roles))))
            embed.add_field(name='Channels:', value="This server has {} channels".format(len(list(server.channels))))
            embed.set_footer(text='{} | {}'.format(server.region, time.strftime("%a %b %D, %Y at %I:%M %p")))
        return Response(embed, delete=60)

##########################################################################
#                             Bot-Info
##########################################################################

    async def c_help(self, cmd=None):
        """
        Provides helpful information
        Usage: {prefix}help [command]
        If a command is omitted, it will return a list of commands
        If a command is given, it will give the docs for that command
        """
        if cmd:
            h = getattr(self, 'c_%s' % cmd, None)
            if not h:
                return Response(":warning: `{}` is not a valid command".format(cmd), delete=10)
            docs = getattr(h, '__doc__', None)
            docs = '\n'.join(l.strip() for l in docs.split('\n'))
            return Response("```\n{}\n```".format(
                docs.format(prefix=self.config.prefix)), reply=True, delete=60)
        else:
            commands = []
            for a in dir(self):
                if a.startswith('c_'):
                    cname = a.replace('c_', '').lower()
                    commands.append("{}{}".format(self.config.prefix, cname))
            return Response("Commands:\n`{}`".format("`, `".join(commands)), delete=60)

    async def c_stats(self):
        """
        Usage: {prefix}stats
        Tells you info about the bot itself.
        """
        '''response = "{}\n__**Uptime:**__ ".format(author.mention)

        # Bot uptime
        m, s = divmod(int(self.bot.get_uptime()), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        _uptime = "**%d** days **%02d** hours **%02d** minutes **%02d** seconds" % (d, h, m, s)

        # Servers
        response += "\nI am currently on **{}** servers, ".format(
            len(self.bot.servers))
        response += "**{}** of which require 2FA.\n".format(
            len([x for x in self.bot.servers if x.mfa_level == 1]))

        # Users
        response += "On these servers I can see **{}** users ".format(
            len(list(self.bot.get_all_members())))
        response += "and **{}** bots.".format(
            len([x for x in self.bot.get_all_members() if x.bot]))

        # Other
        # response += "\n\nPMs: {}".format(len(self.bot.private_channels))
        return Response(response, delete=30)'''

        m, s = divmod(int(self.bot.get_uptime()), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        _uptime = "**%d** days **%02d** hours **%02d** minutes **%02d** seconds" % (d, h, m, s)

        embed = discord.Embed()
        embed.colour = 0xfeb23d
        embed.set_author(name=str('Made by {}'.format(self.config.owner)), url=str('https://dakotamaatman.com/'), icon_url=self.config.owner.avatar_url)
        embed.set_thumbnail(url=self.bot.user.avatar_url)
        embed.add_field(name='Servers', value="I am currently on **{}** servers, and **{}** of which require 2FA.".format(len(self.bot.servers),len([x for x in self.bot.servers if x.mfa_level == 1])))
        embed.add_field(name='Users', value="On these servers I can see **{}** users and **{}** bots.".format(len(list(self.bot.get_all_members())),len([x for x in self.bot.get_all_members() if x.bot])))
        embed.add_field(name='Other', value="\n\nPMs: {}".format(len(self.bot.private_channels)))
        embed.add_field(name='Uptime', value=_uptime)
        embed.set_footer(text='Dev helper: {}'.format(self.config.developer), icon_url=self.config.developer_avatar_url)

        return Response(embed, delete=60)

##########################################################################
#                               TAGS
##########################################################################

    async def c_tags(self):
        """
        Usage: {prefix}tags
        Lists all tags
        """
        if not self.bot.dbfailed:
            cursor = await self.db.get_db().table(self.bot.config.dbtable_tags).run(self.db.db)
            if not cursor.items:
                return Response(":warning: No tags exist (yet)", delete=10)
            tags = [x['name'] for x in cursor.items]
        else:
            tags = load_json(BACKUP_TAGS)
            if not tags:
                return Response(":warning: No tags found in the backup tags file", delete=10)
        return Response(":pen_ballpoint: **Tags**\n`{}`".format('`, `'.join(tags)), delete=60)

    @requires_db
    async def c_createtag(self, message):
        """
        Usage: {prefix}createtag <"name"> <"tag">
        Creates a new tag
        """
        content = re.findall('"([^"]*)"', message.content)
        if len(content) == 2:
            name, content = content
            data = {"name": name, "content": content}
            await self.db.insert(self.config.dbtable_tags, data)
            return Response(":thumbsup:", delete=10)
        else:
            raise InvalidUsage()

    @owner_only
    @requires_db
    async def c_deletetag(self, message):
        """
        Usage: {prefix}deletetag <"name">
        Deletes a tag
        """
        content = re.findall('"([^"]*)"', message.content)
        if len(content) == 1:
            name = content[0]
            delete = await self.db.delete(self.config.dbtable_tags, name)
            if int(delete['skipped']) != 0:
                return Response(":warning: Could not delete `{}`, does not exist".format(name), delete=10)
            return Response(":thumbsup:", delete=10)
        else:
            raise InvalidUsage()

    async def c_tag(self, message, tag):
        """
        Usage: {prefix}tag <name>
        Returns a tag
        """
        content = message.content.replace(
            '{}tag '.format(self.config.prefix), '')
        if not self.bot.dbfailed:
            get = await self.db.get_db().table(self.config.dbtable_tags).get(content).run(self.db.db)
            if get is None:
                return Response(":warning: No tag named `{}`".format(content), delete=10)
            else:
                return Response(get['content'])
        else:
            get = load_json(BACKUP_TAGS)
            if not get:
                return Response(":warning: No tags found in the backup tags file", delete=10)
            else:
                get = get.get(content, default=None)
                if get is None:
                    return Response(":warning: No tag with that name in the backup tags file", delete=10)
                else:
                    return Response(get)

    @owner_only
    @requires_db
    async def c_cleartags(self):
        """
        Clears all tags

        Usage: {prefix}cleartags
        DANGER!!! Clears all tags in the database, this is an @owner_only command
        and should not be used unless absolutely necessary
        """
        await self.db.delete(self.config.dbtable_tags)
        return Response(":thumbsup:", delete=10)

##########################################################################
#                               Mod
##########################################################################

    # async def c_purge(self, channel):
        """
        Usage: {prefix}purge <number> <@user> "reason"

        Deletes a <number> of messages from a channel. If a user is defined,
        will only delete mentioned users messages.
        """
        # fix this to do bulk purge to avoid ratelimits
  
##########################################################################
#                               Admin
##########################################################################

    @owner_only
    async def c_shutdown(self, channel):
        """
        Usage: {prefix}shutdown
        Shuts down the bot
        """
        await self.bot.send_message(channel, ":wave:")
        raise TerminateSignal()

    @owner_only
    async def c_listservers(self, channel):
        """
        Usage: {prefix}listservers
        Lists the servers the bot is on and their ID's
        If greater than 10 servers, sends a text file
        """
        r = "Running on the following servers:"
        limit = 10
        for s in self.bot.servers:
            r += "\n{0.name} ({0.id})".format(s)
            limit = limit - 1
        if limit == 0:
            flo = io.StringIO(r)
            await self.bot.send_file(channel, flo, filename='servers.txt')
            flo.close()
        else:
            return Response(r, delete=10)

    @owner_only
    async def c_leaveserver(self, message, serverid: str):
        """
        Usage: {prefix}leaveserver <server id>
        Leaves the listed server by use of the servers ID
        """
        server = self.bot.get_server(serverid)
        if server:
            await self.bot.leave_server(server)
            return Response(':ok: Bot has left {}'.format(server.name), delete=10)
        elif not server:
            return Response(':exclamation: I am not in that server', delete=10)
        else:
            return

    @owner_only
    async def c_setname(self, name: str):
        """
        Usage: {prefix}setname <name>
        Sets the name of the bot (does not support names with spaces currently)
        """
        await self.bot.edit_profile(username=name)
        msg = ':thumbsup: Changed my name to: **{0}**'.format(name)
        return Response(msg)
