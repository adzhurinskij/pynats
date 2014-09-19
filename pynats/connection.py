# -*- coding: utf-8 -*-
import socket
import json
import time
from pynats.commands import commands, MSG, INFO, PING, PONG, OK
from pynats.subscription import Subscription
from pynats.message import Message
try:
    import urllib.parse as urlparse
except:
    import urlparse

DEFAULT_URI = 'nats://localhost:4222'


class Connection(object):
    """
    A Connection represents a bare connection to a nats-server.
    """
    def __init__(
        self,
        url=DEFAULT_URI,
        name=None,
        ssl_required=False,
        verbose=False,
        pedantic=False
    ):
        self._connect_timeout = None
        self._socket = None
        self._socket_file = None
        self._subscriptions = {}
        self._next_sid = 1
        self._options = {
            'url': urlparse.urlsplit(url),
            'name': name,
            'ssl_required': ssl_required,
            'verbose': verbose,
            'pedantic': pedantic
        }

    def connect(self):
        """
        Connect will attempt to connect to the NATS server. The url can
        contain username/password semantics.
        """
        self._build_socket()
        self._connect_socket()
        self._build_file_socket()
        self._send_connect_msg()

    def _build_socket(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self._connect_timeout)

    def _connect_socket(self):
        SocketError.wrap(self._socket.connect, (
            self._options['url'].hostname,
            self._options['url'].port
        ))

    def _send_connect_msg(self):
        self._send('CONNECT %s' % self._build_connect_config())
        self._recv(INFO)

    def _build_connect_config(self):
        config = {
            'verbose': self._options['verbose'],
            'pedantic': self._options['pedantic'],
            'ssl_required': self._options['ssl_required'],
            'name': self._options['name'],
        }

        if self._options['url'].username is not None:
            config['user'] = self._options['url'].username
            config['pass'] = self._options['url'].password

        return json.dumps(config)

    def _build_file_socket(self):
        self._socket_file = self._socket.makefile('rb')

    def ping(self):
        self._send('PING')
        self._recv(PONG)

    def subscribe(self, subject, callback):
        """
        Subscribe will express interest in the given subject. The subject can
        have wildcards (partial:*, full:>). Messages will be delivered to the
        associated callback.

        Args:
            subject (string): a string with the subject
            callback (function): callback to be called
        """
        s = Subscription(
            sid=self._next_sid,
            subject=subject,
            queue='',
            callback=callback,
            connetion=self
        )

        self._subscriptions[s.sid] = s
        self._send('SUB %s %s %d' % (s.subject, s.queue, s.sid))
        self._next_sid += 1

        return s

    def unsubscribe(self, subscription):
        """
        Unsubscribe will remove interest in the given subject.

        Args:
            subscription (pynats.Subscription): a Subscription object
        """
        self._send('UNSUB %d' % subscription.sid)
        self._subscriptions.pop(subscription.sid)

    def publish(self, subject, msg, reply=None):
        """
        Publish publishes the data argument to the given subject.

        Args:
            subject (string): a string with the subject
            msg (string): payload string
            reply (string): subject used in the reply
        """
        if reply is None:
            command = 'PUB %s %d' % (subject, len(msg))
        else:
            command = 'PUB %s %s %d' % (subject, reply, len(msg))

        self._send(command)
        self._send(msg)

    def wait(self, duration=None, count=0):
        """
        Publish publishes the data argument to the given subject.

        Args:
            duration (float): will wait for the given number of seconds
            count (count): stop of wait after n messages from any subject
        """
        start = time.time()
        total = 0
        while True:
            type, result = self._recv(MSG, PING, OK)
            if type is MSG:
                total += 1
                if self._handle_msg(result) is False:
                    break

                if count and count >= total:
                    break
            elif type is PING:
                self._handle_ping()

            if duration and time.time() - time.time() - start:
                break

    def _handle_msg(self, result):
        data = dict(result.groupdict())
        sid = int(data['sid'])

        msg = Message(
            sid=sid,
            size=int(data['size']),
            data=SocketError.wrap(self._socket_file.readline).strip(),
            reply=data['reply'].strip() if data['reply'] is not None else None
        )

        s = self._subscriptions.get(sid)
        return s.handle_msg(msg)

    def _handle_ping(self):
        self._send('PONG')

    def reconnect(self):
        """
        Close the connection to the NATS server and open a new one
        """
        self.close()
        self.connect()

    def close(self):
        """
        Close will close the connection to the server.
        """
        pass

    def _send(self, command):
        #print 'Send: %s' % command
        SocketError.wrap(self._socket.sendall, command + '\r\n')

    def _recv(self, *expected_commands):
        line = SocketError.wrap(self._socket_file.readline)
        #print 'Recv: %s' % line

        command = self._get_command(line)
        if command not in expected_commands:
            raise UnexpectedResponse(line)

        result = command.match(line)
        if result is None:
            raise UnknownResponse(command.pattern, line)

        return command, result

    def _get_command(self, line):
        values = line.strip().split(' ', 1)

        return commands.get(values[0])


class UnknownResponse(Exception):
    pass


class UnexpectedResponse(Exception):
    pass


class SocketError(Exception):
    @staticmethod
    def wrap(wrapped_function, *args, **kwargs):
        try:
            return wrapped_function(*args, **kwargs)
        except socket.error as err:
            raise SocketError(err)
