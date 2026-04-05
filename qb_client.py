"""qb_client.py — qBittorrent Web API wrapper."""

import asyncio
import qbittorrentapi
from qbittorrentapi.exceptions import APIConnectionError, LoginFailed
import logging

logger = logging.getLogger(__name__)

VALID_STATES = {
    "error", "missingFiles", "uploading", "pausedUP", "queuedUP",
    "stalledUP", "checkingUP", "forcedUP", "allocating", "downloading",
    "metaDL", "pausedDL", "queuedDL", "stalledDL", "checkingDL",
    "forcedDL", "moving", "stoppedDL", "stoppedUP",
}


class QBClient:
    """Persistent qBittorrent client with automatic re-auth on expiry."""

    def __init__(self, config):
        self.config = config
        self._client = None
        self._lock = None  # lazy-created in _get_lock()

    def _get_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _get(self):
        """Return the client, creating it once under the lock."""
        if self._client is None:
            async with self._get_lock():
                if self._client is None:  # double-check after acquiring lock
                    self._client = qbittorrentapi.Client(
                        host=self.config["qb_url"],
                        username=self.config["qb_username"],
                        password=self.config["qb_password"],
                        VERIFY_WEBUI_CERTIFICATE=False,
                    )
        return self._client

    async def _ensure_authenticated(self):
        """Probe auth and re-login on session expiry."""
        c = await self._get()
        async with self._get_lock():
            try:
                c.app_version()  # lightweight probe
            except LoginFailed:
                raise
            except APIConnectionError:
                raise
            except Exception:
                # Session expired or generic auth error
                try:
                    c.auth_log_in()
                except LoginFailed:
                    raise ConnectionError("qBittorrent login failed — check credentials")
                except APIConnectionError:
                    raise
            return c

    async def list_torrents(self, state_filter=None):
        c = await self._ensure_authenticated()
        torrents = c.torrents.info()
        if state_filter:
            invalid = set(state_filter) - VALID_STATES
            if invalid:
                logger.warning("Invalid torrent states ignored: %s", invalid)
            return [t for t in torrents if t.state in state_filter]
        return torrents

    async def add_torrent_url(self, source, save_path=None, paused=False, category=None):
        c = await self._ensure_authenticated()
        try:
            c.torrents_add(
                urls=source,
                save_path=save_path,
                is_paused=paused,
                category=category,
            )
            return True, "Torrent added successfully"
        except Exception as e:
            return False, str(e)

    async def add_torrent_file(self, file_content, save_path=None, paused=False, category=None):
        c = await self._ensure_authenticated()
        try:
            c.torrents_add(
                torrent_files=file_content,
                save_path=save_path,
                is_paused=paused,
                category=category,
            )
            return True, "Torrent file added successfully"
        except Exception as e:
            return False, str(e)
