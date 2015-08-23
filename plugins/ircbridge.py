from will.plugin import WillPlugin
from will.decorators import respond_to, periodic, hear, randomly, route, rendered_template, require_settings
from will import settings

from multiprocessing import Process, Pipe

import irc.client
import urlparse
import logging


STORAGE_KEY = 'irc_config'
REACTOR_LOOP_TIMEOUT = 0.2  # seconds

COMMAND_MESSAGE = 'MESSAGE'
COMMAND_CONNECT = 'CONNECT'
COMMAND_DISCONNECT = 'DISCONNECT'


class IrcPlugin(WillPlugin):

    def __init__(self):
        super(IrcPlugin, self).__init__()
        self.pipe, child_pipe = Pipe()
        self.irc_process = Process(target=self.irc_thread, args=(child_pipe,))
        self.irc_process.start()

    @hear(r"^(?P<text>.+)$", multiline=True)
    def on_message(self, message, text=None):
        room_name = self.get_room_from_message(message)["name"]
        if '\n' in text:
            self.say('Unable to send multiline messages to IRC', message=message, color='red')
            return

        self.send_command_irc_process(
            COMMAND_MESSAGE, room_name, format_message(sender=message.sender.nick, body=text)
        )

    def send_command_irc_process(self, command, room_name, argument=None):
        self.pipe.send_bytes(self.string_encode_message(command, room_name, argument))

    def string_encode_message(self, command, room_name, argument=None):
        return '{cmd}|{room_name};{arg}'.format(
            cmd=command,
            room_name=room_name,
            arg=(argument or '')
        )

    @respond_to(r"^[cC]onnect to irc channel (?P<url>.+)")
    def connect_to_channel(self, message, url):
        room_name = self.get_room_from_message(message)["name"]
        configuration = self.load(STORAGE_KEY, {})

        if room_name in configuration:
            self.say(
                "This room is already connected to the channel: {}".format(
                    configuration[room_name]
                ),
                message=message
            )

        configuration[room_name] = url
        self.save(STORAGE_KEY, configuration)

        self.send_command_irc_process(
            COMMAND_CONNECT, room_name, url
        )

    @respond_to(r"^[dD]isconnect from irc")
    def disconnect_from_channel(self, message):
        room_name = self.get_room_from_message(message)["name"]
        configuration = self.load(STORAGE_KEY, {})
        if room_name in configuration:
            del configuration[room_name]
            self.save(STORAGE_KEY, configuration)

            self.send_command_irc_process(
                COMMAND_DISCONNECT, room_name
            )

    def irc_thread(self, pipe):
        configuration = self.load(STORAGE_KEY, {})
        bot = IrcBot()
        bot.register_message_handler(self.send_to_hipchat_from_irc)
        bot.connect_to_multiple(configuration)
        for connection in bot.connections.values():
            self.send_connection_notification(connection)

        while True:
            try:
                bot.reactor.process_once(timeout=REACTOR_LOOP_TIMEOUT)
                if pipe.poll():
                    encoded_message = pipe.recv_bytes()
                    command, room_name, argument = self.decode_string_message(encoded_message)
                    if command == COMMAND_CONNECT:
                        connection = bot.connect_to_url(room_name, argument)
                        self.send_connection_notification(connection)
                    elif command == COMMAND_MESSAGE:
                        bot.send_public_message(room_name, argument)
                    elif command == COMMAND_DISCONNECT:
                        bot.disconnect(room_name)
                        room = self.get_room_from_name_or_id(room_name)
                        self.say("Disconnected from IRC", room=room)
            except Exception:
                logging.critical('Error managing IRC connection', exc_info=True)

    def decode_string_message(self, encoded_message):
        command, payload = encoded_message.split('|', 1)
        split_payload = payload.split(';', 1)
        room_name = split_payload[0]
        if len(split_payload) > 1:
            argument = split_payload[1]
        else:
            argument = None

        return command, room_name, argument

    def send_to_hipchat_from_irc(self, connection, sender, message_text):
        room = self.get_room_from_name_or_id(connection.name)
        self.say(format_message(sender=sender, body=message_text), room=room)

    def send_connection_notification(self, connection):
        room = self.get_room_from_name_or_id(connection.name)
        self.say("Connected to IRC channel {}".format(connection.channel), room=room)


class IrcBot(object):

    def __init__(self):
        self.reactor = irc.client.Reactor()
        self.reactor.add_global_handler("all_events", self.irc_event_dispatcher, -10)
        self.connections = {}
        self.message_handlers = []

    def connect_to_multiple(self, configuration):
        for connection_name, url in configuration.items():
            self.connect_to_url(connection_name, url)

    def connect_to_url(self, connection_name, url):
        if connection_name in self.connections:
            return

        parsed_url = urlparse.urlparse(url)

        split_netloc = parsed_url.netloc.split('@')
        if len(split_netloc) == 1:
            nickname, hostname = 'hipchat', split_netloc[0]
        elif len(split_netloc) == 2:
            nickname, hostname = split_netloc

        channel = '#' + parsed_url.path.lstrip('/')
        if parsed_url.port:
            port = int(parsed_url.port)
        else:
            port = 6667

        connection = self.reactor.server()
        connection.channel = channel
        connection.name = connection_name
        connection.connect(hostname, port, nickname)
        self.connections[connection_name] = connection
        return connection

    def disconnect(self, connection_name):
        connection = self.connections.get(connection_name)
        if connection is not None:
            connection.disconnect()
            del self.connections[connection_name]

    def register_message_handler(self, handler):
        self.message_handlers.append(handler)

    def irc_event_dispatcher(self, connection, event):
        if event.type == 'welcome':
            connection.join(connection.channel)
        elif event.type == 'pubmsg':
            for handler in self.message_handlers:
                try:
                    handler(connection, event.source.nick, event.arguments[0])
                except Exception as e:
                    print e
        elif event.type == 'privmsg':
            msg = event.arguments[0]
            if not msg.startswith('!'):
                return

            command_handler = getattr(self, 'command_' + msg[1:], None)
            if command_handler is not None:
                command_handler(connection, event)

    def send_public_message(self, connection_name, message_text):
        connection = self.connections.get(connection_name)
        if connection:
            connection.privmsg(connection.channel, message_text)

    def command_help(self, connection, event):
        connection.privmsg(
            event.source.nick,
            'Available Commands - !status: show bot status information'
            ', !help: show this message'
        )

    def command_status(self, connection, event):
        connection.privmsg(event.source.nick, "Connected to {room_name}".format(room_name=connection.name))

def format_message(sender, body):
    message_format = getattr(settings, 'IRC_MESSAGE_TEMPLATE', "[{sender}] {body}")
    return message_format.format(sender=sender, body=body)
