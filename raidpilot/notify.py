"""Optional status messages to your own Discord webhook."""
import json
import threading
import urllib.request


def send(url: str, text: str, log=None, wait: bool = False):
    if not url:
        return None

    def work():
        request = urllib.request.Request(
            url,
            data=json.dumps({"content": text[:1900], "username": "RaidPilot"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "RaidPilot"},
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
            return True
        except OSError as exc:
            if log:
                log(f"Discord message failed: {exc}", "warn")
            return False

    if wait:
        return work()
    threading.Thread(target=work, daemon=True).start()
    return None


def short(number: int) -> str:
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.0f}k"
    return str(number)
