"""Read-only merchant evidence. A public page is never a verified checkout quote."""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

from lane_mcp import LaneError
from website_image_references import PublicFetcher, public_url


def merchant_url(value):
    try:
        url = public_url(value)
        p = urlsplit(url)
        if p.scheme != "https" or p.fragment:
            raise ValueError()
        return url
    except ValueError:
        raise LaneError("Use a public HTTPS merchant page without login details or a fragment.") from None


def host(value):
    return urlsplit(merchant_url(value)).hostname.removeprefix("www.")


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


async def inspect_page(value):
    url = merchant_url(value)
    fetcher = PublicFetcher()
    try:
        for _ in range(5):
            status, headers, raw = await fetcher.one(url)
            if 300 <= status < 400 and headers.get("location"):
                url = merchant_url(headers["location"])
                continue
            if status != 200 or not headers["content-type"].startswith(("text/html", "text/plain")):
                return {"url": url, "status": "needs_review", "excerpt": "",
                        "note": "Open the merchant page to confirm the item, account and final total."}
            parser = PageText()
            parser.feed(raw.decode("utf-8", errors="replace"))
            excerpt = " ".join(" ".join(parser.parts).split())[:3000]
            return {"url": url, "status": "page_read", "excerpt": excerpt,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "note": "Public page retrieved. Price, taxes, availability and target account are not verified."}
        raise ValueError()
    except Exception:
        return {"url": merchant_url(value), "status": "needs_review", "excerpt": "",
                "note": "The public page could not be read. Open the merchant page to verify the purchase."}
    finally:
        await fetcher.close()


def inspect(value):
    try:
        return asyncio.run(asyncio.wait_for(inspect_page(value), timeout=35))
    except TimeoutError:
        return {"url": merchant_url(value), "status": "needs_review", "excerpt": "",
                "note": "The merchant page timed out. Open it to verify the purchase."}


def matches_merchant(name, details):
    if not isinstance(name, str):
        return False
    if name.strip().casefold() == details.get("merchant_name", "").strip().casefold():
        return True
    try:
        return host("https://" + name.removeprefix("https://").rstrip("/")) == host(details["merchant_url"])
    except LaneError:
        return False


def link(url, account, merchant_name=None):
    """The merchant page, its name and the intended account; never an amount."""
    if not isinstance(account, str) or not 1 <= len(account.strip()) <= 200:
        raise LaneError("Specify the intended merchant account, or 'Not account-based'. Never include credentials.")
    url = merchant_url(url)
    name = host(url) if merchant_name is None else merchant_name
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 253:
        raise LaneError("Provide the merchant name shown on the reviewed page.")
    return {"merchant_url": url, "merchant_name": name.strip(), "account": account.strip()}


def details(url, max_amount_cents, account, merchant_name=None):
    if type(max_amount_cents) is not int or not 1 <= max_amount_cents <= 100000000:
        raise LaneError("Provide the user's explicit maximum total in USD cents, including taxes and fees.")
    return {**link(url, account, merchant_name), "max_amount_cents": max_amount_cents, "currency": "USD"}
