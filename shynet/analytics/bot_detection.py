"""Bot classification helpers.

Shynet upstream only flags a session as a robot when the `user_agents`
library self-reports `is_bot` (plus a couple of Googlebot/spider special
cases). That catches polite, self-identifying crawlers but misses the bulk
of modern non-human traffic: AI training crawlers, SEO scrapers, and HTTP
client libraries that send a non-browser user agent.

This module centralises detection so the ingest path can record both a
device type (for the existing "device types" breakdown) and an authoritative
`is_bot` flag with a short, human-readable reason for the dashboard.
"""

# Substrings (matched case-insensitively against the raw user agent) that
# identify a bot the `user_agents` library frequently misses. Kept explicit
# and conservative to avoid false positives against real browser UAs.
KNOWN_BOT_UA_SUBSTRINGS = [
    # --- AI / LLM crawlers ---
    "gptbot",
    "oai-searchbot",
    "chatgpt-user",
    "claudebot",
    "claude-web",
    "anthropic-ai",
    "ccbot",
    "google-extended",
    "perplexitybot",
    "perplexity-user",
    "amazonbot",
    "applebot-extended",
    "bytespider",
    "cohere-ai",
    "diffbot",
    "imagesiftbot",
    "omgili",
    "timpibot",
    "youbot",
    "meta-externalagent",
    "meta-externalfetcher",
    # --- SEO / commercial crawlers ---
    "ahrefsbot",
    "semrushbot",
    "dotbot",
    "mj12bot",
    "petalbot",
    "dataforseobot",
    "blexbot",
    "seekport",
    "serpstatbot",
    "barkrowler",
    # --- Generic non-browser HTTP clients / tooling ---
    "python-requests",
    "python-urllib",
    "aiohttp",
    "httpx",
    "go-http-client",
    "okhttp",
    "axios",
    "node-fetch",
    "got (https",
    "libwww-perl",
    "curl/",
    "wget/",
    "java/",
    "jakarta",
    "apache-httpclient",
    "headlesschrome",
    "phantomjs",
    "scrapy",
    "guzzlehttp",
    "winhttp",
    "powershell",
    # --- Generic giveaways ---
    "facebookexternalhit",
    "telegrambot",
    "whatsapp",
    "slackbot",
    "discordbot",
    "bingpreview",
]


def _matches_known_bot(user_agent_lower):
    return any(token in user_agent_lower for token in KNOWN_BOT_UA_SUBSTRINGS)


def classify(user_agent, ua, tracker, treat_pixel_as_bot=False):
    """Return (device_type, is_bot, bot_reason) for a new session.

    - ``device_type`` keeps upstream semantics: it is ``ROBOT`` for any
      user-agent-detected bot, otherwise the detected hardware class. This
      preserves the existing "device types" breakdown.
    - ``is_bot`` is the authoritative flag the dashboard segments on. It is a
      superset of ``device_type == "ROBOT"`` and additionally captures the
      expanded crawler list and (optionally) no-JS / pixel-only clients.
    - ``bot_reason`` is a short tag explaining the classification, surfaced
      in the UI.
    """
    user_agent_lower = (user_agent or "").lower()

    ua_library_bot = (
        ua.is_bot
        or (ua.browser.family or "").strip().lower() == "googlebot"
        or (ua.device.family or ua.device.model or "").strip().lower() == "spider"
    )
    known_bot = _matches_known_bot(user_agent_lower)
    empty_ua = len((user_agent or "").strip()) == 0

    # Device type (unchanged ordering from upstream).
    if ua_library_bot or known_bot:
        device_type = "ROBOT"
    elif ua.is_mobile:
        device_type = "PHONE"
    elif ua.is_tablet:
        device_type = "TABLET"
    elif ua.is_pc:
        device_type = "DESKTOP"
    else:
        device_type = "OTHER"

    is_bot = False
    bot_reason = ""
    if ua_library_bot:
        is_bot, bot_reason = True, "ua-library"
    elif known_bot:
        is_bot, bot_reason = True, "known-crawler"
    elif empty_ua:
        is_bot, bot_reason = True, "no-user-agent"
    elif treat_pixel_as_bot and tracker == "PIXEL":
        # The noscript pixel only fires for clients that don't run JavaScript.
        # Optional because it can also catch privacy-conscious humans.
        is_bot, bot_reason = True, "no-js"

    return device_type, is_bot, bot_reason
