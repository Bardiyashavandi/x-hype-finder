"""Live X account bio "automated"-label check (tasks.md T060, FR-013,
contracts/external-integrations.md § X Posting).

Checked at the instant the mode switches to autonomous (src/posting/mode.py's
`switch_to_autonomous`) — never cached, since a label that was present a week
ago proves nothing about right now. Also hosts `build_x_client`, the shared
`tweepy.Client` factory every posting module needs (bio check here, the
publish call in src/posting/publish.py) — kept in one place so credential
wiring isn't duplicated per-module (mirrors src/agent/summarize.py's inline
`anthropic.Anthropic(api_key=...)` construction, just centralized since
multiple posting modules share it).

`build_x_client` takes per-user `XCredentials` (src/config.py,
`load_x_credentials_for_user`), never the shared `Config` — every user posts
as their own X account, so building a client from anything shared across
users would let one user's drafts publish through another user's account
(FR-015, User Story 5).
"""

from __future__ import annotations

import tweepy

from src.config import XCredentials

# FR-013: the bio must carry this label, checked case-insensitively as a
# plain substring (e.g. "🤖 automated" or "[Automated account]" both count).
AUTOMATED_LABEL = "automated"


def build_x_client(credentials: XCredentials) -> tweepy.Client:
    """Construct a `tweepy.Client` from this one user's own env-sourced OAuth
    1.0a user-context credentials (FR-021, Constitution V — never hardcoded;
    FR-015 — never another user's). Construction itself makes no network call."""
    return tweepy.Client(
        consumer_key=credentials.api_key,
        consumer_secret=credentials.api_secret,
        access_token=credentials.access_token,
        access_token_secret=credentials.access_token_secret,
    )


def check_bio_has_automated_label(x_client: tweepy.Client) -> bool:
    """Live-read the authenticated account's bio and check for a visible
    "automated" label (FR-013)."""
    response = x_client.get_me(user_fields=["description"])
    description = response.data.description if response.data is not None else None
    return AUTOMATED_LABEL in (description or "").lower()
