import discord
import asyncio
import inspect
import os
from os.path import basename
import sys
import time
import logging
import traceback

import random
# from random import choice as randchoice

from functools import wraps

from .config import Config, load_json, dump_json, Yaml
from .deets import VERSION, USER_AGENT,BACKUP_WARNING1, BACKUP_WARNING2, BACKUP_ACTIONS, BACKUP_TAGS
from .commands import Commands, Response
from .exceptions import BotException, InvalidUsage, PermissionsError, HelpfulError, HelpfulWarning, Signal, RestartSignal, TerminateSignal
from .database import Database
from .req import HTTPClient

log = logging.getLogger(__name__)

user = discord.User()

games = ['>>marco', '>>ping', '>>id']


class BayMax(discord.Client):

    def __init__(self):
        self.config = Config('config/config.ini')
        self.cached_app_info = None
        self.exit_signal = None
        self.cached_client_id = None

        super().__init__()
        self.http.user_agent = USER_AGENT
        self.db = Database(self)

        self.req = HTTPClient(loop=self.loop)
        self.commands = Commands(self)

        log.info("K.I.T.T. ({}). Connecting...".format(VERSION))

    def run(self):
        try:
            super().run(self.config.token)
        except discord.errors.LoginFailure as e:
            log.critical('Could not log in: {}'.format(e))
            os._exit(1)
        except discord.errors.HTTPException as e:
            log.critical(e)

    def format_bool(self, boolean):
        """
        Returns a string based on bool value
        """
        return ['no', 'yes'][boolean]

    async def generate_invite_link(self, *, permissions=None, server=None):
        if not self.cached_client_id:
            appinfo = await self.application_info()
            self.cached_client_id = appinfo.id

        return discord.utils.oauth_url(self.cached_client_id, permissions=permissions, server=server)

    def ensure_appinfo(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            await self._cache_app_info()
            # noinspection PyCallingNonCallable
            return await func(self, *args, **kwargs)
        return wrapper

    def _get_owner(self, *, server=None, voice=False):
        return discord.utils.find(
            lambda m: m.id == self.config.owner.id and (m.voice_channel if voice else True),
            server.members if server else self.get_all_members()
        )

    async def _cache_app_info(self, *, update=False):
        if not self.cached_app_info and not update and self.user.bot:
            log.info('Caching app info.')
            self.cached_app_info = await self.application_info()

        return self.cached_app_info

    async def send_message(self, dest, content=None, embed=None, *, tts=False, delete=0, also_delete=None):
        """
        Overrides discord.py's function for sending a message
        """
        if content is None and embed is None:
            log.warning('send_message was called but no content was given')
            return
        if isinstance(content, discord.Embed):
            embed = content
            content = None

        msg = None
        try:
            if embed:
                msg = await super().send_message(dest, embed=embed)
            else:
                msg = await super().send_message(dest, content, tts=tts)
            log.debug(
                'Sent message ID {} in #{}'.format(msg.id, dest.name))

            if msg and delete and self.config.delete:
                asyncio.ensure_future(self._delete_after(msg, delete))
            if also_delete and self.config.delete_invoking and isinstance(also_delete, discord.Message):
                asyncio.ensure_future(self._wait_delete_msg(also_delete, delete))

        except discord.Forbidden:
            log.warning(
                "No permission to send a message to #{}".format(dest.name))
        except discord.NotFound:
            log.warning(
                "Could not find channel #{} to send a message to".format(dest.name))
        except discord.HTTPException as e:
            log.warning(
                "Problem sending a message in #{}: {}".format(dest.name, e))
        return msg

    async def edit_message(self, message, content, *, delete=0):
        """
        Overrides discord.py's function for editing a message
        """
        msg = None
        try:
            msg = await super().edit_message(message, content)
            log.debug(
                'Edited message ID {} in #{}'.format(msg.id, msg.channel))
            if msg and delete and self.config.delete:
                asyncio.ensure_future(self._delete_after(msg, delete))
        except discord.Forbidden:
            log.warning(
                "No permission to edit a message in #{}".format(message.channel))
        except discord.NotFound:
            log.warning(
                "Could not find message ID {} to edit".format(message.id))
        except discord.HTTPException as e:
            log.warning(
                "Problem editing a message in #{}: {}".format(message.channel, e))
        return msg

    async def delete_message(self, msg):
        """
        Overrides discord.py's function for deleting a message
        """
        try:
            await super().delete_message(msg)
            log.debug(
                'Deleted message ID {} in #{}'.format(msg.id, msg.channel.name))
        except discord.Forbidden:
            log.warning(
                "No permission to delete a message in #{}".format(msg.channel.name))
        except discord.HTTPException as e:
            log.warning(
                "Problem deleting a message in #{}: {}".format(msg.channel.name, e))

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.delete_message(message)

    async def _delete_after(self, msg, time):
        """
        Deletes a message after a given amount of time
        """
        log.debug(
            "Scheduled message ID {} to delete ({}s)".format(msg.id, time))
        await asyncio.sleep(time)
        await self.delete_message(msg)

    async def restart(self):
        self.exit_signal = RestartSignal()
        await self.logout()

    def restart_threadsafe(self):
        asyncio.run_coroutine_threadsafe(self.restart(), self.loop)

    async def logout(self):
        return await super().logout()

    @ensure_appinfo
    async def _on_ready_sanity_checks(self):
        # config/permissions async validate?
        await self._scheck_configs()

    async def _scheck_configs(self):
        log.info('Validating config')
        await self.config.async_validate(self)
####################################################################################################################################################################################
# Doing Database Stuff
    async def database(self):
        self.dbfailed = False
        if not self.config.nodatabase:
            connect = await self.db.connect(self.config.rhost, self.config.rport, self.config.ruser, self.config.rpass)
            if connect:
                # Create needed tables
                await self.db.create_table(self.config.dbtable_warning1, primary='author')

                # Dump any existing warnings to backup file
                if self.config.backupwarning1:
                    log.info('Backing up existing warning1 to JSON file...')
                    cursor = await self.db.get_db().table(self.config.dbtable_warning1).run(self.db.db)
                    current_backup = load_json(BACKUP_WARNING1)
                    for i in cursor.items:
                        current_backup = i['author']
                    dump_json(BACKUP_WARNING1, current_backup)
                    log.info('First warnings have been backed up to {} in case of a database outage'.format(BACKUP_WARNING1))
                await self.db.create_table(self.config.dbtable_warning2, primary='author')

                # Dump any existing warnings to backup file
                if self.config.backupwarning2:
                    log.info('Backing up existing warning2 to JSON file...')
                    cursor = await self.db.get_db().table(self.config.dbtable_warning2).run(self.db.db)
                    current_backup = load_json(BACKUP_WARNING2)
                    for i in cursor.items:
                        current_backup = i['author']
                    dump_json(BACKUP_WARNING2, current_backup)
                    log.info('Secound warning have been backed up to {} in case of a database outage'.format(BACKUP_WARNING2))
                await self.db.create_table(self.config.dbtable_actions, primary='author')

                # Dump any existing actions to backup file
                if self.config.backupactions:
                    log.info('Backing up existing actions to JSON file...')
                    cursor = await self.db.get_db().table(self.config.dbtable_actions).run(self.db.db)
                    current_backup = load_json(BACKUP_ACTIONS)
                    for i in cursor.items:
                        name = i['author']
                        current_backup[name] = i['action']
                    dump_json(BACKUP_ACTIONS, current_backup)
                    log.info('Actions have been backed up to {} in case of a database outage'.format(BACKUP_ACTIONS))
                await self.db.create_table(self.config.dbtable_tags, primary='name')

                # Dump any existing tags to backup file
                if self.config.backuptags:
                    log.info("Backing up existing tags to JSON file...")
                    cursor = await self.db.get_db().table(self.config.dbtable_tags).run(self.db.db)
                    current_backup = load_json(BACKUP_TAGS)
                    for i in cursor.items:
                        name = i['name']
                        current_backup[name] = i['content']
                    dump_json(BACKUP_TAGS, current_backup)
                    log.info("Tags have been backed up to {} in case of a database outage".format(BACKUP_TAGS))
            else:
                log.warning('A database connection could not be established')
                self.dbfailed = True
        else:
            log.warning('Skipped database connection per configuration file')
            self.dbfailed = True
        if self.dbfailed:
            log.warning('As the database is unavailable, tags cannot be created or deleted, but tags that exist in the backup JSON file can be triggered.')
        self.db.ready = True
        print(flush=True)

####################################################################################################################################################################################
# Utilities
    def get_uptime(self):
        """
        Returns the uptime of the bot
        """
        return time.time() - self.started

    async def spam_prevention(self, message):
        author = message.author
        channel = message.channel
        content = message.content.strip()
        server = message.server
        permissions = author.server_permissions
#        t_end = time.time() + 10

        entry = 0
        # checking for mention spamers
        entry += len(message.mentions) + len(message.role_mentions)
#        mutedrole = discord.utils.get(server.roles, name='Muted')
        if not permissions.ban_members | permissions.manage_messages:
#            while ((entry <= int(self.config.mention_level)) or (t_end > int(time.time))) and (entry != 0):
#                if entry < 6:
#                    print(entry)
#                if t_end == time.time:
#                    print('Spam Prevention Triggered')
            if entry > int(self.config.mention_level):
                get1 = await self.db.get_db().table(self.config.dbtable_warning1).get(author.id).run(self.db.db)
                get2 = await self.db.get_db().table(self.config.dbtable_warning2).get(author.id).run(self.db.db)
                if get1 is None:
                    data = {"author": author.id}
                    await self.db.insert(self.config.dbtable_warning1, data)
                    await self.send_message(channel, "User <@{}> please do not spam mentions. This is your first warning.".format(author.id))
                elif get2 is None:
                    data = {"author": author.id}
                    await self.db.insert(self.config.dbtable_warning2, data)
                    await self.send_message(channel, "User <@{}> please do not spam mentions. This is your Secound and Last warning.".format(author.id))
                else:
                    data = {"author": author.id, "action": 'muted'}
                    await self.db.insert(self.config.dbtable_actions, data)
                    await self.send_message(channel, ":no_entry_sign: User <@{}> has just been muted for mentioning too many users. :hammer:".format(author.id))
                    await self.send_message(channel, ">mute <@{}> for mass pinging members/staff".format(author.id))
                    log.warning('Muted {} for mentionning {} users. On {}'.format(author, entry, message.server))

    async def cycle_playing(self):
        status = None
        while True:
            status = random.choice(games)
            await self.change_presence(game=discord.Game(name=status))
            await asyncio.sleep(30)

    async def cycle_server_icon(self):
        server = self.get_server(self.config.auto_cycle) # need to get this to be settable throught the config file we we stop fighting with the server id luminary lmao
        path = os.getcwd() + '/assets'
        files = os.listdir(path)
        while True:
            with open('{0}/{1}'.format(path, files[0]), 'rb') as f:
                await self.edit_server(server, icon=f.read())

            del files[0]

            if not files:
                files = os.listdir(path)

            log.info('Cycled Server Icon')  # to {}'.format(os.path.splitext(os.path.basename(__file__))[0])) ***FIX THIS TO SAY WHAT IT CHANGED TO, IT'S FAIRLY CLOSE***
            await asyncio.sleep(600)

####################################################################################################################################################################################
# Bot Its self
    async def on_ready(self):
        # logchan = discord.utils.get(self.get_all_channels(), id='000000000000000000')
        self.started = time.time()
        await self._on_ready_sanity_checks()
        log.info('')
        await self.database()
        log.info("Bot started at {}".format(time.strftime('%Y %b %d %X')))  # I'm not using %c because I like my custom format more
        log.info('Connected!')
        log.info('Version: {}'.format(VERSION))
        log.info("Bot:   {0}#{1}/{2}{3}".format(
            self.user.name,
            self.user.discriminator,
            self.user.id,
            ' [BOT]' if self.user.bot else ' [Userbot]'
        ))

        owner = self._get_owner()
        log.info('Owner: {0}#{1}/{2}'.format(
            owner.name,
            owner.discriminator,
            owner.id
        ))
        log.info('')
        log.info('Info:')
        if not self.servers:
            log.error('The bot is not on any servers. Use this link:\n{}'.format(await self.generate_invite_link(permissions=discord.Permissions.all())))
        else:
            log.info('Running on the following servers:')
            for server in self.servers:
                print('   - {} ({})'.format(server, server.id))
        log.info('')
        log.info('Command Prefix: {}'.format(self.config.prefix))
        log.info('Delete Messages: {}'.format(self.config.delete))
        log.info('Delete Invoking Messages: {}'.format(self.config.delete))
        log.info('')
        # await self.send_message(logchan, ":heart:")
        asyncio.ensure_future(self.cycle_playing())
        asyncio.ensure_future(self.cycle_server_icon())

    async def on_message(self, message):
        author = message.author
        channel = message.channel
        content = message.content.strip()
        server = message.server

        if author == self.user:
            return
            # ignores the bot itself if it should send the invoking command for
            # reasons unknown, probably when i mess up the code some how

        if channel.is_private:
            await self.send_message(channel, "Sorry {}, but I can't be used here.".format(author.mention))
            return  # ignores private channels, not sure if sending message is needed or works. will test later
            # getting number of mentions in message and if over taking action

        await self.spam_prevention(message)

        if not content.startswith(self.config.prefix):
            return  # if comment doesn't start with set prefix, ignores message
        cmd, *args = content.split()
        cmd = cmd[len(self.config.prefix):].lower().strip()

        h = getattr(self.commands, 'c_{}'.format(cmd), None)

        if not h:
            return

        s = inspect.signature(h)
        p = s.parameters.copy()
        kw = {}
        if p.pop('message', None):
            kw['message'] = message
        if p.pop('channel', None):
            kw['channel'] = message.channel
        if p.pop('author', None):
            kw['author'] = message.author
        if p.pop('server', None):
            kw['server'] = message.server
        if p.pop('args', None):
            kw['args'] = args
        if p.pop('user_mentions', None):
            kw['user_mentions'] = list(map(message.server.get_member, message.raw_mentions))

        ae = []
        for key, param in list(p.items()):
            doc_key = '[%s=%s]' % (
                key, param.default) if param.default is not inspect.Parameter.empty else key
            ae.append(doc_key)
            if not args and param.default is not inspect.Parameter.empty:
                p.pop(key)
                continue
            if args:
                v = args.pop(0)
                kw[key] = v
                p.pop(key)

        try:
            if p:
                raise InvalidUsage()

            r = await h(**kw)
            if r and isinstance(r, Response):
                content = r.content
                await self.send_message(message.channel, content, delete=r.delete, also_delete=message)

        except HelpfulError as e:
            log.error("Error in {0}: {1.__class__.__name__}: {1.message}".format(cmd, e))

            delete = e.delete if self.config.delete else None
            alsodelete = message if self.config.delete_invoking else None

            await self.send_message(
                message.channel,
                '```\n{}\n```'.format(e.message),
                delete=delete,
                also_delete=alsodelete
            )

        except PermissionsError as e:
            log.error("Error in {0}: {1.__class__.__name__}: {1.message}".format(cmd, e))

            delete = e.delete if self.config.delete else None
            alsodelete = message if self.config.delete_invoking else None

            await self.send_message(
                message.channel,
                '\n{}\n'.format(e.message),
                delete=delete,
                also_delete=alsodelete
            )

        except InvalidUsage as e:
            docs = getattr(h, '__doc__', None)
            docs = '\n'.join(l.strip() for l in docs.split('\n'))
            docs = ":warning: Incorrect usage.\n```\n{}\n```".format(
                docs.format(prefix=self.config.prefix))

            delete = e.delete if self.config.delete else None
            alsodelete = message if self.config.delete_invoking else None

            log.error(docs)

            return await self.send_message(message.channel, docs, delete=10, also_delete=alsodelete)

        except Signal:
            raise

        except Exception:
            log.warning("Exception in on_message")
            await self.send_message(message.channel, '```\n{}\n```'.format(traceback.format_exc()))

    async def on_error(self, event, *args, **kwargs):
        et, e, es = sys.exc_info()
        traceback.print_exc()


if __name__ == '__main__':
    bot = BayMax
    bot.run()
