import os
from datetime import datetime
import subprocess
import select
from pipes import quote
import paramiko
import socket

class SSHConnectionError(Exception):
    pass


class Shell(object):
    def _run(self, user_command, stdout, stderr):
        raise NotImplementedError("Shell class is not self-standing.")

    def info_string(self):
        return "no-info"

    def run(self, user_command, stdout=None, stderr=None):
        rc = -1
        with open(os.devnull, "w") as devnull:
            rc = self._run(user_command, stdout or devnull, stderr or devnull)

        return rc

    def run_expensive(self, user_command):
        """
        Return exit status together with standard outputs in string variables.
        Note that this can pretty easily waste a lot of memory.

        :param user_command:
            Command to be run as string (note: pipes.quote).

        :returns:
            Tripple (rc, stdout, stderr).  Stdout and stderr are strings, those
            might be pretty large.
        """
        raise NotImplementedError


class SSHConnection(Shell):
    user = 'root'
    host = 'localhost'
    port = 22
    identityfile = None

    def __init__(self, username, host, port=22, identityfile=None):
        self.host = host
        self.user = username
        self.port = port
        if identityfile:
            self.identityfile = os.path.expanduser(identityfile)

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def info_string(self):
        return 'raw-ssh-{0}@{1}'.format(self.user, self.host)


class SSHConnectionRaw(SSHConnection):
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
        # For now we don't allow password auth.
        '-o', 'PasswordAuthentication=no',
        '-q',
    ]

    def __init__(self, *args, **kwargs):
        super(SSHConnectionRaw, self).__init__(*args, **kwargs)

    def _ssh_base(self, additional_options=None):
        if additional_options is None:
            additional_options = []
        cmd = ['ssh'] + additional_options + self.ssh_options

        if self.control_path:
            cmd = cmd + ['-o', 'ControlPath=' + self.control_path]

        if self.identityfile:
            cmd = cmd + ['-o', 'IdentityFile=' + self.identityfile]

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

        if subprocess.call(self._ssh_base(['-fMN'])) != 0:
            raise SSHConnectionError("Can't connect to ssh server.")

    def disconnect(self):
        subprocess.call(self._ssh_base(['-O', 'stop']))
        self.control_path = None


    def _run(self, user_command, stdout, stderr):
        real_command = self._ssh_base() + [user_command]
        proc = subprocess.Popen(real_command, stdout=stdout, stderr=stderr)
        retval = proc.wait()
        if retval == 255:
            if not os.path.exists(os.path.expanduser(self.control_path)):
                raise SSHConnectionError("Connection broke.")

        return retval


    def run_expensive(self, user_command):
        real_command = self._ssh_base() + [user_command]
        proc = subprocess.Popen(real_command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode == 255:
            if not os.path.exists(os.path.expanduser(self.control_path)):
                raise SSHConnectionError("Connection broke.")

        return proc.returncode, stdout, stderr


class SSHConnectionParamiko(SSHConnection):
    conn = None

    def connect(self):
        self.conn = paramiko.SSHClient()
        self.conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.conn.connect(
                hostname=self.host, port=self.port,
                username=self.user,
                key_filename=self.identityfile)
        except paramiko.AuthenticationException as err:
            raise SSHConnectionError(str(err))
        except paramiko.SSHException as err:
            raise SSHConnectionError(str(err))
        except socket.error as err:
            raise SSHConnectionError(str(err))
        except paramiko.ssh_exception.NoValidConnectionsError as err:
            raise SSHConnectionError(str(err))


    def _run(self, user_command, stdout, stderr):
        try:
            transport = self.conn.get_transport()
            channel = transport.open_session()
            channel.exec_command(user_command)
        except paramiko.SSHException:
            raise SSHConnectionError("Paramiko connection failure.")


        status = 1
        try:
            # Drats!  How clumsy the API of paramiko is.
            while True:
                something_found = False

                # Just to slow down things a bit.
                _, _, _ = select.select([channel], [], [], 10)

                if channel.recv_ready():
                    data = channel.recv(256)
                    if len(data) != 0:
                        stdout.buffer.write(data)
                        stdout.flush()
                        something_found = True

                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(256)
                    if len(data) != 0:
                        stderr.buffer.write(data)
                        stderr.flush()
                        something_found = True

                if not something_found:
                    break

            status = channel.recv_exit_status()
        except socket.timeout:
            raise SSHConnectionError('Socket timeout error.')

        if status == -1:
            raise SSHConnectionError('Paramiko connection broke.')

        return status


    def run_expensive(self, user_command):
        try:
            _, cout, cerr = self.conn.exec_command(user_command)
            return cout.channel.recv_exit_status(), cout.read(), cerr.read()

        except paramiko.SSHException:
            raise SSHConnectionError('Paramiko connection broke.')


    def disconnect(self):
        pass
