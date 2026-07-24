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
"""

from __future__ import annotations

import tweepy

from src.config import Config

# FR-013: the bio must carry this label, checked case-insensitively as a
# plain substring (e.g. "🤖 automated" or "[Automated account]" both count).
AUTOMATED_LABEL = "automated"


def build_x_client(config: Config) -> tweepy.Client:
    """Construct a `tweepy.Client` from env-sourced OAuth 1.0a user-context
    credentials (FR-021, Constitution V — never hardcoded). Construction
    itself makes no network call."""
    return tweepy.Client(
        consumer_key=config.x_api_key,
        consumer_secret=config.x_api_secret,
        access_token=config.x_access_token,
        access_token_secret=config.x_access_token_secret,
    )


def check_bio_has_automated_label(x_client: tweepy.Client) -> bool:
    """Live-read the authenticated account's bio and check for a visible
    "automated" label (FR-013)."""
    response = x_client.get_me(user_fields=["description"])
    description = response.data.description if response.data is not None else None
    return AUTOMATED_LABEL in (description or "").lower()
