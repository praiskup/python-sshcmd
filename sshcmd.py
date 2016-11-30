import time
from subprocess import call

class SSHConnection:
    user = 'root'
    host = 'localhost'

    control_path = None
    ssh_options = [
        '-o', 'ControlMaster=auto',
        # Don't bother with host key checking.
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ControlPersist=600',
        # One hour deadline.
        '-o', 'ServerAliveInterval=300',
        '-o', 'ServerAliveCountMax=12',
    ]

    def _ssh_base(self, additional_options=None):
        if additional_options is None:
            additional_options = []
        cmd = ['ssh'] + additional_options + self.ssh_options
        if self.control_path:
            cmd = cmd + self.control_path
        cmd.append(self._conn_id())
        return cmd

    def _conn_id(self):
        return '{0}@{1}'.format(self.user, self.host)

    def connect(self):
        self.control_path = [
            '-o',
            'ControlPath=~/.ssh/control/ssh-%r@%h:%p_{0}' .format(time.time()),
        ]
        call(self._ssh_base(['-fMN']))

    def disconnect(self):
        call(self._ssh_base(['-O', 'stop']))
        self.control_path = []

    def run(self, user_command):
        call(self._ssh_base() + [user_command])

    def __init__(self, username, host):
        self.host = host
        self.user = username
