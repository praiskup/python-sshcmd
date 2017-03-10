import os
from datetime import datetime
from subprocess import call


class SSHConnectionError(Exception):
    pass


class Shell:
    def _run(self, user_command):
        raise NotImplementedError("Shell class is not self-standing.")

    def info_string(self):
        return "no-info"

    def run(self, user_command):
        return self._run(user_command)


class SSHConnection(Shell):
    user = 'root'
    host = 'localhost'

    control_path = None
    ssh_options = [
        '-o', 'ControlMaster=auto',
        # Don't bother with host key checking.
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        # When not explcitly disconnect()ed, garbage collect the background
        # process and socket file after two hours.
        '-o', 'ControlPersist=7200',
        # One hour deadline for particular connection.
        '-o', 'ServerAliveInterval=300',
        '-o', 'ServerAliveCountMax=12',
        '-q',
    ]

    def info_string(self):
        return '{0}@{1}'.format(self.user, self.host)

    def _ssh_base(self, additional_options=None):
        if additional_options is None:
            additional_options = []
        cmd = ['ssh'] + additional_options + self.ssh_options
        if self.control_path:
            cmd = cmd + ['-o', 'ControlPath=' + self.control_path]
        cmd.append(self._conn_id())
        return cmd

    def _conn_id(self):
        return '{0}@{1}'.format(self.user, self.host)

    def connect(self):
        dt = datetime.now()
        timestamp = "{year}-{month}-{day}_{h:02d}:{m:02d}:{s:02d}_{us}".format(
            h=dt.hour,
            m=dt.minute,
            s=dt.second,
            us=dt.microsecond,
            year=dt.year,
            month=dt.month,
            day=dt.day,
        )
        self.control_path = '~/.ssh/control/{0}_ssh-{1}@{2}:{3}'.format(
            timestamp,
            self.user,
            self.host,
            22,
        )

        if call(self._ssh_base(['-fMN'])) != 0:
            raise SSHConnectionError("Can't connect to ssh server.")

    def disconnect(self):
        call(self._ssh_base(['-O', 'stop']))
        self.control_path = None

    def _run(self, user_command):
        real_command = self._ssh_base() + [user_command]
        retval = call(real_command)
        if retval == 255:
            if not os.path.exists(os.path.expanduser(self.control_path)):
                raise SSHConnectionError("Connection broke.")

        return retval

    def __init__(self, username, host):
        self.host = host
        self.user = username
