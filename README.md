# qBittorrent Telegram Bot

A Telegram bot that lets you manage qBittorrent torrents from chat, inspired by [deluge-telegramer](https://github.com/noam09/deluge-telegramer).

## Features

- Add torrents via magnet link, URL, or `.torrent` file upload
- List torrents by state (all, downloading, seeding, paused)
- Conversation flow with category selection for download location
- Persistent Telegram menu button for easy access
- Whitelist-based access control
- Auto-detect magnet links and torrent files sent directly in chat
- Persistent qBittorrent client (single connection, auto-re-auth)

## Commands

| Command | Description |
| --- | --- |
| `/add` | Add a new torrent |
| `/addpaused` | Add a new torrent paused |
| `/list` | List all torrents |
| `/down` | List downloading torrents |
| `/up` | List seeding torrents |
| `/paused` | List paused torrents |
| `/cancel` | Cancel the current operation |
| `/help` | Show this help |

## Prerequisites

- Python 3.9+ (tested on 3.13)
- qBittorrent with WebUI enabled
- A Telegram bot token from [@BotFather](https://t.me/botfather)

## Setup

### 1. Clone and install

```bash
git clone https://github.com/yourusername/qbittorrent-telegram-bot.git
cd qbittorrent-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy `config.json` and edit it:

```bash
cp config.json.example config.json
nano config.json
```

Key fields:

| Key | Description |
| --- | --- |
| `qb_url` | qBittorrent WebUI URL (e.g. `http://localhost:8080`) |
| `qb_username` | qBittorrent username |
| `qb_password` | qBittorrent password |
| `categories` | Named save-path directories for the /add flow |
| `torrent_list_limit` | Max torrents shown per message (default: 10) |
| `torrent_format` | `detailed` or `brief` |

### 3. Set environment variables

```bash
cp env.example .env
nano .env
```

```
BOT_TOKEN=your-bot-token-from-botfather
BOT_ALLOWED_USERS=123456789
```

Get your Telegram user ID from [@MyIDbot](https://t.me/myidbot) by sending `/getid`.

### 4. Run

```bash
source .venv/bin/activate
python3 bot.py
```

On first launch the bot sends you the persistent menu.

### 5. Register commands (via @BotFather)

Send `/setcommands` to [@BotFather](https://t.me/botfather) and paste:

```
add - Add a new torrent
addpaused - Add a new torrent paused
list - List all torrents
down - List downloading torrents
up - List seeding torrents
paused - List paused torrents
cancel - Cancel the current operation
help - Show this help
```

## Running as a systemd service (Linux)

```bash
sudo cp qbitbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start qbitbot
sudo systemctl enable qbitbot
```

Edit `qbitbot.service` first to match your paths and user.

```bash
# Check status
sudo systemctl status qbitbot

# View logs
sudo journalctl -u qbitbot -f
```

## Architecture

```
qbittorrent-telegram-bot/
├── bot.py            # Main entry, handler registration, conversations
├── qb_client.py      # Persistent qBittorrent API wrapper (auth re-use)
├── formatters.py     # Torrent info formatting + message chunking
├── config.json       # Your config (not committed)
├── config.json       # Example config (committed)
├── requirements.txt  # Python dependencies
├── qbitbot.service   # systemd unit file
└── README.md
```

## License

MIT
