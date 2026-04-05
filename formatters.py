"""formatters.py — Format torrent info for Telegram messages."""

from datetime import timedelta

EMOJI = {
    "downloading":  "⏬",
    "uploading":    "⏫",
    "forcedDL":     "⏬",
    "forcedUP":     "⏫",
    "pausedDL":     "⏸️",
    "pausedUP":     "⏸️",
    "queuedDL":     "⏯️",
    "queuedUP":     "⏯️",
    "checkingDL":   "🔍",
    "checkingUP":   "🔍",
    "error":        "❗",
    "missingFiles": "⚠️",
    "stalledDL":    "⚙️",
    "stalledUP":    "⚙️",
    "metaDL":       "📡",
    "allocating":   "💾",
    "moving":       "📦",
    "stoppedDL":    "⏹️",
    "stoppedUP":    "⏹️",
}


def _fmt_size(b):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def _fmt_speed(bps):
    return _fmt_size(bps) + "/s" if bps else "0 B/s"


def _fmt_eta(s):
    if s <= 0:
        return "∞"
    return str(timedelta(seconds=int(s)))


def format_torrent_detail(t):
    """Format a single torrent with full details (plain text)."""
    state = getattr(t, "state", "unknown")
    emoji = EMOJI.get(state, "❓")
    name = getattr(t, "name", "Unknown")
    progress = getattr(t, "progress", 0) * 100
    size = _fmt_size(getattr(t, "size", 0))
    downloaded = _fmt_size(getattr(t, "completed", 0))
    dlspeed = _fmt_speed(getattr(t, "dlspeed", 0))
    upspeed = _fmt_speed(getattr(t, "upspeed", 0))
    eta = _fmt_eta(getattr(t, "eta", -1))
    peers = f"{getattr(t, 'num_leechs', '?')}/{getattr(t, 'num_seeds', '?')}"
    ratio = f"{getattr(t, 'ratio', 0):.2f}"

    lines = [
        f"{emoji} {name}",
        f"  Progress: {progress:.1f}%  |  {downloaded} / {size}",
        f"  ↓ {dlspeed}  ↑ {upspeed}  Ratio: {ratio}",
        f"  Peers: {peers}  |  ETA: {eta}",
    ]
    return "\n".join(lines)


def format_torrent_brief(t):
    """Format a single torrent in one line."""
    state = getattr(t, "state", "unknown")
    emoji = EMOJI.get(state, "❓")
    name = getattr(t, "name", "Unknown")
    progress = getattr(t, "progress", 0) * 100
    size = _fmt_size(getattr(t, "size", 0))
    return f"{emoji} {name} — {progress:.1f}% of {size}"


def format_torrent_list(torrents, limit=10, fmt="detailed"):
    """Format a list of torrents into a Telegram-ready message string."""
    if not torrents:
        return "No torrents found."

    formatter = format_torrent_detail if fmt == "detailed" else format_torrent_brief

    # Sort: downloading > seeding > others, then by progress desc
    state_order = {"downloading": 0, "forcedDL": 0, "metaDL": 1,
                   "uploading": 2, "forcedUP": 2}
    sorted_t = sorted(torrents,
                      key=lambda t: (state_order.get(getattr(t, "state", ""), 3),
                                     -getattr(t, "progress", 0)))

    entries = [formatter(t) for t in sorted_t[:limit]]
    text = "\n\n".join(entries)

    if len(sorted_t) > limit:
        text += f"\n\n…and {len(sorted_t) - limit} more (use a filter command)"

    return text


def chunk_text(text, max_len=4096):
    """Split text into chunks safe for Telegram's 4096-char limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    # Split on double newlines to avoid cutting a torrent entry in half
    blocks = text.split("\n\n")
    current = ""

    for block in blocks:
        candidate = (current + "\n\n" + block).strip() if current else block
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
                current = ""
            # If a single block is too long, split it on single newlines
            if len(block) > max_len:
                lines = block.split("\n")
                line_chunk = ""
                for line in lines:
                    test = (line_chunk + "\n" + line).strip() if line_chunk else line
                    if len(test) <= max_len:
                        line_chunk = test
                    else:
                        if line_chunk:
                            chunks.append(line_chunk)
                        if len(line) > max_len:
                            # Hard split: break long line into multiple chunks
                            for i in range(0, len(line), max_len):
                                chunks.append(line[i:i+max_len])
                            line_chunk = ""
                        else:
                            line_chunk = line
                if line_chunk:
                    current = line_chunk
            else:
                current = block

    if current:
        chunks.append(current)

    return chunks
