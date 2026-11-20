"""android_app.py — is this request from the Android app? (2026-11-19)

The staff app is going into the Google Play Store as an Android app: a
Capacitor WebView shell that loads system.mysolutionist.app. Google Play
doesn't let an Android app sell its own plans or add-ons outside Play
billing, or push people to buy them somewhere else, so the app already
hides every buy button (solutionist-studio #1646, src/core/lib/nativeApp.ts).
Chief's replies are written here, on the server, so Chief needs the same
rule. Under Google's current US rules we may tell people in PLAIN WORDS
where a plan is changed, as long as we give no tappable link (a link puts
us in Play's fee-bearing external content links program).

Kevin, 2026-11-19 ("build it that way"), inside the Android app only:
  · Chief never brings up upgrading, buying a plan, credits, extra storage
    or extra logins, or adding a card; never gives a link or a markdown link
    for it; never emits an action that starts a checkout;
  · it may say plainly which plan includes a feature ("That's part of the
    Growing plan. Your church is on Small right now.");
  · only when the person asks how to get it or how to change their plan:
    the account owner hears, in plain words and with no link, "Plans are
    changed in Settings → Billing and plan. Sign in at mysolutionist.app in
    a browser to do it."; anyone else (an office login, a collaborator)
    hears that the plan is managed by the owner, by name when Chief knows
    it, and to ask them.
Outside the app (a browser, the installed web app) nothing changes.

HOW THE SERVER KNOWS. Every request from the app's WebView carries a user
agent containing `SolutionistAndroid/` (the shell appends
`SolutionistAndroid/1`, solutionist-studio #1644). AndroidAppMarker, a pure
ASGI layer registered in kmj_intake_automation.py, reads it once per
request into a ContextVar and resets it when the request ends; the Chief
endpoints take a ChatRequest, not a Request, so this is how they ask:
in_android_app(). Tasks the request starts (the stream's turn, the sample
Chief's answer) copy the context when they are created, so they see it too.

WHERE THE WORDS GO. Never into a cached prompt segment: [[CHIEF_GLOBAL_SPLIT]]
and [[CHIEF_CACHE_SPLIT]] are prompt-cache boundaries, and a per-request
line above them would break caching for every business. into_turn_tail()
appends the block to the END of the built prompt, which is inside the last,
uncached segment for every prompt shape (4-, 3-, 2-segment and single), and
is the last thing the model reads before the conversation, so it outranks
the manual's billing lines above it.

Switched by CHIEF_ANDROID_APP: on (the default) | off. Off answers False
everywhere, and Chief speaks in the app exactly as it does in a browser.
"""
from __future__ import annotations

import contextvars
import os
from typing import Any, Optional

UA_MARK = "SolutionistAndroid/"
ENV = "CHIEF_ANDROID_APP"

# This request's answer: True only while a request from the app is being
# served (AndroidAppMarker sets and resets it). The scheduler, a webhook and
# every browser request read the default.
_IN_APP: contextvars.ContextVar[bool] = contextvars.ContextVar("android_app", default=False)


def enabled() -> bool:
    return (os.environ.get(ENV) or "on").strip().lower() not in ("off", "0", "false", "no")


def is_app_user_agent(ua: Any) -> bool:
    return UA_MARK in str(ua or "")


def in_android_app() -> bool:
    """True while serving a request from the Android app (and the switch is on)."""
    return bool(_IN_APP.get()) and enabled()


def set_in_app(value: bool) -> contextvars.Token:
    """For code (and tests) that need to say it themselves; reset with the token."""
    return _IN_APP.set(bool(value))


def reset(token: contextvars.Token) -> None:
    _IN_APP.reset(token)


def _user_agent(scope) -> str:
    for k, v in scope.get("headers") or []:
        if k.lower() == b"user-agent":
            return v.decode("latin-1")
    return ""


class AndroidAppMarker:
    """Pure ASGI (never BaseHTTPMiddleware): marks an HTTP request from the
    Android app, and clears the mark when the request ends. Never touches
    the request or the response, so streaming is untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        token = _IN_APP.set(is_app_user_agent(_user_agent(scope)))
        try:
            return await self.app(scope, receive, send)
        finally:
            _IN_APP.reset(token)


# ─── What Chief is told inside the app ────────────────────────────────

HEADING = "INSIDE THE ANDROID APP"

OWNER_ANSWER = ("Plans are changed in Settings → Billing and plan. "
                "Sign in at mysolutionist.app in a browser to do it.")


def _clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def chief_block(*, is_owner: bool, owner_name: Optional[str] = None) -> str:
    """The rules for Chief's main turn, chosen for who is asking. '' outside the app."""
    if not in_android_app():
        return ""
    if is_owner:
        how = ("this is the account owner. Say, in plain words and with no link: "
               f"\"{OWNER_ANSWER}\" Write mysolutionist.app as plain text: never as a "
               "markdown link, and never with https:// or www in front.")
    else:
        owner = _clean(owner_name)[:80]
        who = f"{owner}, the account owner" if owner else "the account owner"
        ask = owner or "the account owner"
        how = (f"this login is not the account owner. Say the plan is managed by {who}, "
               f"and suggest they ask {ask}. Don't tell them where plans are changed.")
    return (
        f"{HEADING} — this person is using Solutionist's Android app, and Google Play's "
        "rules apply to this reply. They outrank anything above about plans, prices or "
        "billing.\n"
        "- Never bring up upgrading, choosing or changing a plan, prices, credits or "
        "credit packs, extra storage, extra logins or seats, or adding a card. Don't "
        "suggest or offer them, and don't end a reply by pointing to them, even when "
        "something isn't on their plan or they are out of credits.\n"
        "- Never give a link for any of that: no markdown link like [words](https://…), "
        "no https:// address, no button, and no action that starts a checkout or opens "
        "billing.\n"
        "- You may say plainly which plan includes something and which plan they are on "
        "now, once and with no push, for example: \"That's part of the Growing plan. "
        "Your church is on Small right now.\"\n"
        "- If a result or record you read tells them to upgrade, buy something or add a "
        "card, leave that part out and keep only which plan includes it.\n"
        f"- Only when they ask how to get it or how to change their plan: {how}\n"
        "- The church's or business's own money is not affected: its giving, invoices, "
        "products, payment links and sign-ups work as usual.\n"
    )


def into_turn_tail(system: Any, block: str) -> Any:
    """The prompt with `block` at its very end: inside the uncached turn tail
    for every prompt shape, never in a cached segment. Unchanged when there
    is no block (outside the app) or the prompt isn't a string."""
    if not block or not isinstance(system, str):
        return system
    return system.rstrip() + "\n\n" + block.strip() + "\n"


def block_in(system: Any) -> str:
    """The app block a built prompt carries ('' when none): for a path that
    rebuilds the prompt from pieces (the backup brain) and must keep it."""
    text = str(system or "")
    at = text.rfind(HEADING + " — ")
    return text[at:].strip() if at >= 0 else ""


def rewrite_rule() -> str:
    """For the call that rewrites Chief's reply after its actions ran."""
    if not in_android_app():
        return ""
    return ("\n\nINSIDE THE ANDROID APP: this reply is read in Solutionist's Android app. "
            "Leave out anything that tells them to upgrade, choose or change a plan, buy "
            "credits, storage or logins, or add a card, and any link for those. Keep plain "
            "facts about which plan includes something, and keep any plain-words line the "
            "draft already has about where plans are changed, with no link.")


def opener_rule() -> str:
    """For the first track's opening sentence."""
    if not in_android_app():
        return ""
    return ("\nThis person is in the Android app: never mention upgrading, plans, prices, "
            "credits, storage, logins or adding a card in the opening.")


def defer_rule(token: str) -> str:
    """For a quick lane that answers without the full rules (the fast answer,
    the headline, the voice preview): send anything about plans or buying
    to the full turn, which has them."""
    if not in_android_app():
        return ""
    return ("\nThis person is in the Android app. If the message is about plans, prices, "
            "upgrading, billing, credits, storage, logins or adding a card, reply exactly "
            f"{token} and nothing else.")


def wording(web: str, app: str) -> str:
    """A server-written line: the app's wording inside the Android app, else the web's."""
    return app if in_android_app() else web
