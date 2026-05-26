"""
find_feeds.py
-------------
Tests common RSS/Atom feed URL patterns against a list of candidate
domains. Prints which URLs return valid feeds.

Run:
    python find_feeds.py

For each candidate, tries common paths (/feed, /rss, /rss.xml, /atom.xml,
/feed.xml). Reports HTTP status + content type. A 200 OK with an
xml content type = working RSS feed.
"""

from __future__ import annotations

import urllib.error
import urllib.request


# Add or remove candidates here. The script tries every common feed path
# against each domain.
CANDIDATES = [
    # Already confirmed working
    "https://www.bensbites.com",
    
    # Alternative AI newsletters to test
    "https://www.latent.space",            # Latent Space
    "https://magazine.sebastianraschka.com",  # Ahead of AI
    "https://www.interconnects.ai",         # Interconnects
    "https://importai.substack.com",        # Import AI (Substack — usually has RSS)
    "https://thebatch.deeplearning.ai",     # The Batch
    "https://www.theneurondaily.com",       # The Neuron
    "https://www.superhuman.ai",            # Superhuman AI
    "https://www.smol.ai",                  # AI News (smol.ai)
    "https://buttondown.com/ainews",        # AI News alt
    
    # Try Substack pattern for several
    "https://lastweekin.ai",                # Last Week in AI
    "https://www.theaireport.io",           # AI Report
]

# Paths to test against each domain.
PATHS = [
    "/feed",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
    "/feed/",
    "/feeds/posts/default",  # blogspot
    "/index.xml",            # hugo / jekyll
]

USER_AGENT = "FeedDiscoveryBot/1.0 (testing feed URLs)"
TIMEOUT = 8.0


def test_url(url: str) -> tuple[int, str, int]:
    """
    Return (status_code, content_type, body_bytes).
    On error, status_code is 0 and content_type is the error message.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(2048)  # just enough to identify the format
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                len(body),
            )
    except urllib.error.HTTPError as e:
        return (e.code, f"http error", 0)
    except urllib.error.URLError as e:
        return (0, f"url error: {e.reason}", 0)
    except Exception as e:
        return (0, f"error: {e}", 0)


def looks_like_feed(content_type: str, body_size: int) -> bool:
    """Heuristic: is this likely a real RSS/Atom feed?"""
    ct = content_type.lower()
    return body_size > 0 and (
        "xml" in ct or "rss" in ct or "atom" in ct
    )


def main() -> None:
    print(f"Testing {len(CANDIDATES)} domains × {len(PATHS)} paths\n")
    print(f"{'URL':<55} {'Status':<8} {'Content-Type':<35} {'Likely feed?'}")
    print("-" * 110)

    working: list[str] = []

    for base in CANDIDATES:
        any_hit = False
        for path in PATHS:
            url = base.rstrip("/") + path
            status, ct, size = test_url(url)
            is_feed = looks_like_feed(ct, size) if status == 200 else False
            marker = "  ← WORKS" if is_feed else ""

            print(f"{url:<55} {status:<8} {ct[:34]:<35} {marker}")

            if is_feed:
                working.append(url)
                any_hit = True

        if any_hit:
            print()  # blank line between domains with hits

    print()
    print(f"Found {len(working)} working feed URL(s):")
    for url in working:
        print(f"  {url}")

    if not working:
        print("(none — these newsletters may have disabled RSS)")


if __name__ == "__main__":
    main()
