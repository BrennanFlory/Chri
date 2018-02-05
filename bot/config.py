import os
import configparser
import ruamel.yaml as yaml
import json
import logging

from .exceptions import HelpfulError

log = logging.getLogger(__name__)

def load_json(file):
    """Loads a JSON file and returns it as a dict"""
    with open(file) as f:
        return json.load(f)


def dump_json(file, array):
    """Dumps a dict to a JSON file"""
    with open(file, 'w') as f:
        return json.dump(array, f)

class Config():
    def __init__(self, config_file):
        self.config_file = config_file
        if not os.path.isfile(config_file):
            log.critical("'{}'' does not exist".format(config_file))
            raise Shutdown()

        config = configparser.ConfigParser(interpolation=None)
        config.read(config_file, encoding='utf-8')

        confsections = {"Credentials", "Permissions", "Chat", "General", "Moderation"}.difference(config.sections())
        if confsections:
            raise HelpfulError(
                "One or more required config sections are missing.",
                "Fix your config.  Each [Section] should be on its own line with "
                "nothing else on it.  The following sections are missing: {}".format(
                    ', '.join(['[%s]' % s for s in confsections])
                ),
                preface="An error has occured parsing the config:\n"
            )

        self._confpreface = "An error has occured reading the config:\n"
        self._confpreface2 = "An error has occured validating the config:\n"

        #[Auth]
        self.token = config.get('Credentials', 'Token', fallback=ConfigDefaults.token)

        #[Permissions]
        self.owner = config.get('Permissions', 'OwnerID', fallback=ConfigDefaults.OwnerID)
        self.developer = config.get('Permissions', 'DeveloperName', fallback=ConfigDefaults.DeveloperName)
        self.developer_avatar_url = config.get('Permissions', 'DeveloperAvatar', fallback=ConfigDefaults.DeveloperAvater)

        #[Chat]
        self.prefix = config.get('Chat', 'Prefix', fallback=ConfigDefaults.prefix)

        #[General]
        self.delete = config.getboolean('General', 'Delete', fallback=ConfigDefaults.delete)
        self.delete_invoking = config.getboolean('General', 'DeleteInvoking', fallback=ConfigDefaults.delete_invoking)
        self.auto_cycle = config.get('General', 'auto_cycle', fallback=ConfigDefaults.auto_cycle)

        #[Database]
        self.rhost = config.get('Database', 'Host', fallback='localhost')
        self.rport = config.getint('Database', 'Port', fallback=28015)
        self.ruser = config.get('Database', 'User', fallback='admin')
        self.rpass = config.get('Database', 'Password', fallback='')
        self.rname = config.get('Database', 'Name', fallback='turbo')

        # [Advanced]
        self.nodatabase = config.getboolean('Advanced', 'NoDatabase', fallback=False)
        self.dbtable_warning1 = config.get('Advanced', 'DbTable_Warning1', fallback='warning1')
        self.backupwarning1 = config.getboolean('Advanced', 'BackupWarning1', fallback=True)

        self.dbtable_warning2 = config.get('Advanced', 'DbTable_Warning2', fallback='warning2')
        self.backupwarning2 = config.getboolean('Advanced', 'BackupWarning2', fallback=True)

        self.dbtable_actions = config.get('Advanced', 'DbTable_Actions', fallback='actions')
        self.backupactions = config.getboolean('Advanced', 'BackupActions', fallback=True)

        self.dbtable_tags = config.get('Advanced', 'DbTable_Tags', fallback='tags')
        self.backuptags = config.getboolean('Advanced', 'BackupTags', fallback=True)

        #[Moderation]
        self.mention_level = config.get('Moderation', 'MentionLevel', fallback=ConfigDefaults.mention_level)

        log.debug("Loaded '{}'".format(config_file))
        self.run_check()

    def run_check(self):
        if not self.token:
            raise HelpfulError(
                "No login credentials were specified in the config.",

                "Please fill in Token field. "
                "The Token field is for Bot accounts only.",
                preface=self._confpreface
            )


        if self.owner:
            self.owner = self.owner.lower()

            if self.owner.isdigit():
                if int(self.owner) < 10000:
                    raise HelpfulError(
                        "An invalid OwnerID was set: {}".format(self.owner),

                        "Correct your OwnerID.  The ID should be just a number, approximately "
                        "18 characters long.",
                        preface=self._confpreface
                    )

            elif self.owner == 'auto':
                pass # defer to async check

            else:
                self.owner = None

        if not self.owner:
            raise HelpfulError(
                "No OwnerID was set.",
                "Please set the OwnerID option in {}".format(self.config_file),
                preface=self._confpreface
            )

        if not self.developer:
            raise HelpfulError(
                "No DeveloperName was set.",
                "Please set the DeveloperName option in {}".format(self.config_file),
                preface=self._confpreface
            )

        if not self.developer_avatar_url:
            raise HelpfulError(
                "No DeveloperAvater was set.",
                "Please set the DeveloperAvater option in the {}".format(self.config_file),
                preface=self._confpreface
            )

        if not self.prefix:
            raise HelpfulError(
                "Please provide a command prefix.",
                preface=self._confpreface
            )
            os._exit(1)

    async def async_validate(self, bot):
        log.debug("Validating options...")

        if self.owner == 'auto':
            if not bot.user.bot:
                raise HelpfulError(
                    "Invalid parameter \"auto\" for OwnerID option.",

                    "Only bot accounts can use the \"auto\" option.  Please "
                    "set the OwnerID in the config.",

                    preface=self._confpreface2
                )

            self.owner = bot.cached_app_info.owner
            self.owner.id = bot.cached_app_info.owner.id
            log.info("Aquired owner id via API")

        if self.owner == bot.user.id:
            raise HelpfulError(
                "Your OwnerID is incorrect or you've used the wrong credentials.",

                "The bot's user ID and the id for OwnerID is identical.  "
                "This is wrong.  The bot needs its own account to function, "
                "meaning you cannot use your own account to run the bot on.  "
                "The OwnerID is the id of the owner, not the bot.  "
                "Figure out which one is which and use the correct information.",

                preface=self._confpreface2
            )

        if self.developer == bot.user.id:
            raise HelpfulError(
                "Your DeveloperName is incorrect or you've used the wrong credentials.",

                "The bot's user Name and the name for DeveloperName is identical.  "
                "This is wrong.  The bot needs its own account to function, "
                "meaning you cannot use your own account to run the bot on.  "
                "The DeveloperName is the name of the owner, not the bot.  "
                "Figure out which one is which and use the correct information.",

                preface=self._confpreface2
            )

class ConfigDefaults:
    config_file = 'config/config.ini'
    json_file = 'data/data.json'

    email = None
    password = None
    token = None
    OwnerID = None
    DeveloperName = None
    DeveloperAvater = None
    prefix = '!'
    delete = True
    delete_invoking = True
    auto_cycle = None
    mention_level = 10

class Yaml:

    """
    Class for handling YAML
    """

    def parse(filename):
        """
        Parse a YAML file
        """
        try:
            with open(filename) as f:
                try:
                    return yaml.load(f)
                except yaml.YAMLError as e:
                    log.critical("Problem parsing {} as YAML: {}".format(
                        filename, e))
                    return None
        except FileNotFoundError:
            log.critical("Problem opening {}: File was not found".format(filename))
            return None
