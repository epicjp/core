import atexit
import logging
import os
import signal
import sys

import core.services
from core.emulator.session import Session
from core.services.coreservices import ServiceManager


def signal_handler(signal_number, _):
    """
    Handle signals and force an exit with cleanup.

    :param int signal_number: signal number
    :param _: ignored
    :return: nothing
    """
    logging.info("caught signal: %s", signal_number)
    sys.exit(signal_number)


signal.signal(signal.SIGHUP, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGUSR1, signal_handler)
signal.signal(signal.SIGUSR2, signal_handler)


class CoreEmu:
    """
    Provides logic for creating and configuring CORE sessions and the nodes within them.
    """

    def __init__(self, config=None):
        """
        Create a CoreEmu object.

        :param dict config: configuration options
        """
        # set umask 0
        os.umask(0)

        # configuration
        if config is None:
            config = {}
        self.config = config

        # session management
        self.sessions = {}

        # load services
        self.service_errors = []
        self.load_services()

        # catch exit event
        atexit.register(self.shutdown)

    def load_services(self):
        # load default services
        self.service_errors = core.services.load()

        # load custom services
        service_paths = self.config.get("custom_services_dir")
        logging.debug("custom service paths: %s", service_paths)
        if service_paths:
            for service_path in service_paths.split(","):
                service_path = service_path.strip()
                custom_service_errors = ServiceManager.add_services(service_path)
                self.service_errors.extend(custom_service_errors)

    def shutdown(self):
        """
        Shutdown all CORE session.

        :return: nothing
        """
        logging.info("shutting down all sessions")
        sessions = self.sessions.copy()
        self.sessions.clear()
        for _id in sessions:
            session = sessions[_id]
            session.shutdown()

    def create_session(self, _id=None, _cls=Session):
        """
        Create a new CORE session.

        :param int _id: session id for new session
        :param class _cls: Session class to use
        :return: created session
        :rtype: EmuSession
        """
        if not _id:
            _id = 1
            while _id in self.sessions:
                _id += 1
        session = _cls(_id, config=self.config)
        logging.info("created session: %s", _id)
        self.sessions[_id] = session
        return session

    def delete_session(self, _id):
        """
        Shutdown and delete a CORE session.

        :param int _id: session id to delete
        :return: True if deleted, False otherwise
        :rtype: bool
        """
        logging.info("deleting session: %s", _id)
        session = self.sessions.pop(_id, None)
        result = False
        if session:
            logging.info("shutting session down: %s", _id)
            session.shutdown()
            result = True
        else:
            logging.error("session to delete did not exist: %s", _id)

        return result
