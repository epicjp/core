import json
import logging
import os
import time
from tempfile import NamedTemporaryFile

from core import utils
from core.emulator.enumerations import NodeTypes
from core.errors import CoreCommandError
from core.nodes.base import CoreNode


class LxdClient:
    def __init__(self, name, image, run):
        self.name = name
        self.image = image
        self.run = run
        self.pid = None

    def create_container(self):
        self.run(f"lxc launch {self.image} {self.name}")
        data = self.get_info()
        self.pid = data["state"]["pid"]
        return self.pid

    def get_info(self):
        args = f"lxc list {self.name} --format json"
        output = self.run(args)
        data = json.loads(output)
        if not data:
            raise CoreCommandError(-1, args, f"LXC({self.name}) not present")
        return data[0]

    def is_alive(self):
        try:
            data = self.get_info()
            return data["state"]["status"] == "Running"
        except CoreCommandError:
            return False

    def stop_container(self):
        self.run(f"lxc delete --force {self.name}")

    def create_cmd(self, cmd):
        return f"lxc exec -nT {self.name} -- {cmd}"

    def create_ns_cmd(self, cmd):
        return f"nsenter -t {self.pid} -m -u -i -p -n {cmd}"

    def check_cmd(self, cmd, wait=True, shell=False):
        args = self.create_cmd(cmd)
        return utils.cmd(args, wait=wait, shell=shell)

    def copy_file(self, source, destination):
        if destination[0] != "/":
            destination = os.path.join("/root/", destination)

        args = f"lxc file push {source} {self.name}/{destination}"
        self.run(args)


class LxcNode(CoreNode):
    apitype = NodeTypes.LXC.value

    def __init__(
        self,
        session,
        _id=None,
        name=None,
        nodedir=None,
        bootsh="boot.sh",
        start=True,
        server=None,
        image=None,
    ):
        """
        Create a LxcNode instance.

        :param core.emulator.session.Session session: core session instance
        :param int _id: object id
        :param str name: object name
        :param str nodedir: node directory
        :param str bootsh: boot shell to use
        :param bool start: start flag
        :param core.emulator.distributed.DistributedServer server: remote server node
            will run on, default is None for localhost
        :param str image: image to start container with
        """
        if image is None:
            image = "ubuntu"
        self.image = image
        super().__init__(session, _id, name, nodedir, bootsh, start, server)

    def alive(self):
        """
        Check if the node is alive.

        :return: True if node is alive, False otherwise
        :rtype: bool
        """
        return self.client.is_alive()

    def startup(self):
        """
        Startup logic.

        :return: nothing
        """
        with self.lock:
            if self.up:
                raise ValueError("starting a node that is already up")
            self.makenodedir()
            self.client = LxdClient(self.name, self.image, self.host_cmd)
            self.pid = self.client.create_container()
            self.up = True

    def shutdown(self):
        """
        Shutdown logic.

        :return: nothing
        """
        # nothing to do if node is not up
        if not self.up:
            return

        with self.lock:
            self._netif.clear()
            self.client.stop_container()
            self.up = False

    def termcmdstring(self, sh="/bin/sh"):
        """
        Create a terminal command string.

        :param str sh: shell to execute command in
        :return: str
        """
        return f"lxc exec {self.name} -- {sh}"

    def privatedir(self, path):
        """
        Create a private directory.

        :param str path: path to create
        :return: nothing
        """
        logging.info("creating node dir: %s", path)
        args = f"mkdir -p {path}"
        return self.cmd(args)

    def mount(self, source, target):
        """
        Create and mount a directory.

        :param str source: source directory to mount
        :param str target: target directory to create
        :return: nothing
        :raises CoreCommandError: when a non-zero exit status occurs
        """
        logging.debug("mounting source(%s) target(%s)", source, target)
        raise Exception("not supported")

    def nodefile(self, filename, contents, mode=0o644):
        """
        Create a node file with a given mode.

        :param str filename: name of file to create
        :param contents: contents of file
        :param int mode: mode for file
        :return: nothing
        """
        logging.debug("nodefile filename(%s) mode(%s)", filename, mode)

        directory = os.path.dirname(filename)
        temp = NamedTemporaryFile(delete=False)
        temp.write(contents.encode("utf-8"))
        temp.close()

        if directory:
            self.cmd(f"mkdir -m {0o755:o} -p {directory}")
        if self.server is not None:
            self.server.remote_put(temp.name, temp.name)
        self.client.copy_file(temp.name, filename)
        self.cmd(f"chmod {mode:o} {filename}")
        if self.server is not None:
            self.host_cmd(f"rm -f {temp.name}")
        os.unlink(temp.name)
        logging.debug("node(%s) added file: %s; mode: 0%o", self.name, filename, mode)

    def nodefilecopy(self, filename, srcfilename, mode=None):
        """
        Copy a file to a node, following symlinks and preserving metadata.
        Change file mode if specified.

        :param str filename: file name to copy file to
        :param str srcfilename: file to copy
        :param int mode: mode to copy to
        :return: nothing
        """
        logging.info(
            "node file copy file(%s) source(%s) mode(%s)", filename, srcfilename, mode
        )
        directory = os.path.dirname(filename)
        self.cmd(f"mkdir -p {directory}")

        if self.server is None:
            source = srcfilename
        else:
            temp = NamedTemporaryFile(delete=False)
            source = temp.name
            self.server.remote_put(source, temp.name)

        self.client.copy_file(source, filename)
        self.cmd(f"chmod {mode:o} {filename}")

    def addnetif(self, netif, ifindex):
        super().addnetif(netif, ifindex)
        # adding small delay to allow time for adding addresses to work correctly
        time.sleep(0.5)
