"""
email_domain_dns.py — what the operator's DNS actually says.

THE GAP THIS CLOSES
  Resend tells us whether IT could verify a domain. It does not tell the
  operator what to do when it couldn't. "Pending" after an hour of
  pasting records is a dead end: was the value trimmed? Was the host
  written as `send.studiok.com.studiok.com`? Is the record simply not
  propagated yet? Every one of those looks identical from the Resend
  status field, and the operator's only recourse today is to open their
  DNS panel and squint.

  This module resolves each expected record ourselves and reports
  EXPECTED vs FOUND, so the setup screen can say "we found a different
  value at resend._domainkey" instead of "pending".

WHAT ELSE LIVES HERE
  - The DMARC record. Resend's domains API returns SPF, DKIM and the
    bounce MX; it does not return DMARC because DMARC is a policy on the
    operator's whole domain, not on the sending subdomain. Gmail and
    Yahoo's 2024 bulk-sender rules made it effectively mandatory, so we
    synthesize a permissive `p=none` record and report on it like the
    others. It is flagged `optional` — verification never waits on it.
  - Provider detection from the domain's nameservers, so the UI can link
    the operator to the right "add a TXT record" guide instead of a
    generic one.

DISCIPLINE
  - Every function that touches the network is async and bounded (4s
    per lookup, all lookups for one domain run concurrently). A DNS
    outage costs the caller a few seconds, never a hang.
  - The comparison helpers are pure and take plain lists, so the
    matching rules are tested without a resolver in the room.
  - Nothing here writes. The router owns the settings blob.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("email_domain_dns")

LOOKUP_TIMEOUT_S = 4.0

# What the platform asks every operator to publish for DMARC. `p=none`
# is monitor-only: nothing gets rejected, reports flow to the operator's
# own mailbox. The graduation to quarantine is a later, deliberate step.
DMARC_POLICY = "v=DMARC1; p=none;"


# ─── Expected records ───────────────────────────────────────────────


def dmarc_record(domain: str) -> Dict[str, Any]:
    """The DMARC TXT record we recommend for `domain`. Same shape as the
    Resend records so the UI renders it in the same list."""
    d = (domain or "").strip().lower().rstrip(".")
    return {
        "record": "DMARC",
        "type": "TXT",
        "name": "_dmarc",
        "value": f"{DMARC_POLICY} rua=mailto:dmarc@{d}",
        "ttl": "Auto",
        "priority": None,
        "status": "pending",
        "optional": True,
    }


def with_dmarc(records: List[Dict[str, Any]], domain: str) -> List[Dict[str, Any]]:
    """Resend's records plus our DMARC row, never duplicated."""
    out = [dict(r) for r in (records or []) if isinstance(r, dict)]
    if any((r.get("record") or "").upper() == "DMARC" for r in out):
        return out
    out.append(dmarc_record(domain))
    return out


def fqdn_for(name: Optional[str], domain: str) -> str:
    """Resend hands back relative hosts ("send", "resend._domainkey").
    Some panels want the absolute form; the resolver always does."""
    d = (domain or "").strip().lower().rstrip(".")
    n = (name or "").strip().lower().rstrip(".")
    if not n or n == "@":
        return d
    if n == d or n.endswith("." + d):
        return n
    return f"{n}.{d}"


# ─── Pure comparison ────────────────────────────────────────────────


def _norm_txt(v: Any) -> str:
    s = str(v or "").strip()
    # A TXT value pasted with surrounding quotes, or one dnspython hands
    # back as several quoted chunks, must compare equal to the bare string.
    s = re.sub(r'"\s*"', "", s)
    s = s.strip('"')
    return re.sub(r"\s+", "", s)


def compare_txt(expected: str, found: List[str], *, case_sensitive: bool) -> Dict[str, Any]:
    """Does any found TXT string equal the expected one? DKIM public keys
    are base64 (case matters); SPF is case-insensitive by RFC."""
    exp = _norm_txt(expected)
    hits = []
    for f in found or []:
        fv = _norm_txt(f)
        if (fv == exp) if case_sensitive else (fv.lower() == exp.lower()):
            hits.append(f)
    return {"found": bool(found), "match": bool(hits)}


def compare_dmarc(found: List[str]) -> Dict[str, Any]:
    """DMARC counts as satisfied when ANY valid DMARC record is published.
    The operator may legitimately run a stricter policy than the one we
    suggest; demanding a byte-exact match would mark a better setup as
    wrong."""
    valid = [f for f in (found or [])
             if _norm_txt(f).lower().startswith("v=dmarc1")]
    return {"found": bool(found), "match": bool(valid)}


def compare_mx(expected_host: str, expected_priority: Any,
               found: List[Tuple[int, str]]) -> Dict[str, Any]:
    exp_host = (expected_host or "").strip().lower().rstrip(".")
    try:
        exp_pri = int(expected_priority) if expected_priority not in (None, "") else None
    except (TypeError, ValueError):
        exp_pri = None
    match = False
    for pri, host in found or []:
        if (host or "").strip().lower().rstrip(".") != exp_host:
            continue
        if exp_pri is None or int(pri) == exp_pri:
            match = True
            break
    return {"found": bool(found), "match": match}


def evaluate_record(rec: Dict[str, Any], found_txt: List[str],
                    found_mx: List[Tuple[int, str]]) -> Dict[str, Any]:
    """One record + what DNS returned for its host → the UI's verdict.

    `found_values` is what we saw, rendered for a human, so the screen
    can show "found: p=MIGfMA0…tYpo" next to the value we asked for."""
    kind = (rec.get("record") or "").upper()
    rtype = (rec.get("type") or "").upper()
    if rtype == "MX":
        verdict = compare_mx(rec.get("value") or "", rec.get("priority"), found_mx)
        shown = [f"{p} {h}" for p, h in (found_mx or [])]
    elif kind == "DMARC":
        verdict = compare_dmarc(found_txt)
        shown = list(found_txt or [])
    else:
        verdict = compare_txt(rec.get("value") or "", found_txt,
                              case_sensitive=(kind == "DKIM"))
        shown = list(found_txt or [])
    return {**verdict, "found_values": shown[:5]}


# ─── Provider detection (pure) ──────────────────────────────────────

# Nameserver suffix → who the operator logs into to add a record. The
# guide links are the providers' own "add a TXT record" pages; a wrong
# guess here costs the operator nothing worse than a generic guide.
_PROVIDERS: List[Tuple[str, str, str, str]] = [
    ("cloudflare.com", "cloudflare", "Cloudflare",
     "https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/"),
    ("domaincontrol.com", "godaddy", "GoDaddy",
     "https://www.godaddy.com/help/add-a-txt-record-19232"),
    ("registrar-servers.com", "namecheap", "Namecheap",
     "https://www.namecheap.com/support/knowledgebase/article.aspx/317/2237/how-do-i-add-txtspfdkimdmarc-records-for-my-domain/"),
    ("squarespacedns.com", "squarespace", "Squarespace",
     "https://support.squarespace.com/hc/en-us/articles/360002101888"),
    ("googledomains.com", "squarespace", "Squarespace (formerly Google Domains)",
     "https://support.squarespace.com/hc/en-us/articles/360002101888"),
    ("wixdns.net", "wix", "Wix",
     "https://support.wix.com/en/article/adding-or-updating-txt-records-in-your-wix-account"),
    ("ui-dns.com", "ionos", "IONOS",
     "https://www.ionos.com/help/domains/configuring-your-dns-settings/"),
    ("ui-dns.de", "ionos", "IONOS",
     "https://www.ionos.com/help/domains/configuring-your-dns-settings/"),
    ("awsdns", "route53", "Amazon Route 53",
     "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-creating.html"),
    ("digitalocean.com", "digitalocean", "DigitalOcean",
     "https://docs.digitalocean.com/products/networking/dns/how-to/manage-records/"),
    ("name.com", "namedotcom", "Name.com",
     "https://www.name.com/support/articles/205188538-adding-a-txt-record"),
    ("hover.com", "hover", "Hover",
     "https://help.hover.com/hc/en-us/articles/217282457-Managing-DNS-records"),
    ("bluehost.com", "bluehost", "Bluehost",
     "https://www.bluehost.com/help/article/dns-management-add-edit-or-delete-dns-entries"),
    ("hostgator.com", "hostgator", "HostGator",
     "https://www.hostgator.com/help/article/how-to-change-dns-zones-mx-cname-and-a-records"),
    ("worldnic.com", "networksolutions", "Network Solutions",
     "https://www.networksolutions.com/help/article/dns-manage-advanced-dns-records"),
    ("porkbun.com", "porkbun", "Porkbun",
     "https://kb.porkbun.com/article/68-how-to-edit-dns-records"),
    ("dnsimple.com", "dnsimple", "DNSimple",
     "https://support.dnsimple.com/articles/manage-txt-record/"),
    ("vercel-dns.com", "vercel", "Vercel",
     "https://vercel.com/docs/projects/domains/managing-dns-records"),
    ("netlify", "netlify", "Netlify",
     "https://docs.netlify.com/domains-https/netlify-dns/dns-records/"),
    ("wordpress.com", "wordpress", "WordPress.com",
     "https://wordpress.com/support/domains/custom-dns/"),
]

GENERIC_GUIDE = "https://resend.com/docs/dashboard/domains/introduction"


def detect_provider(nameservers: List[str]) -> Dict[str, Any]:
    hosts = [(h or "").strip().lower().rstrip(".") for h in (nameservers or [])]
    for host in hosts:
        for suffix, key, name, guide in _PROVIDERS:
            if suffix in host:
                return {"key": key, "name": name, "guide_url": guide,
                        "nameservers": hosts}
    return {"key": None, "name": None, "guide_url": GENERIC_GUIDE,
            "nameservers": hosts}


# ─── Resolver (network) ─────────────────────────────────────────────


def _resolver():
    import dns.resolver  # dnspython
    r = dns.resolver.Resolver()
    r.timeout = LOOKUP_TIMEOUT_S
    r.lifetime = LOOKUP_TIMEOUT_S
    return r


def _txt_sync(name: str) -> List[str]:
    import dns.resolver
    try:
        answers = _resolver().resolve(name, "TXT")
    except dns.resolver.NXDOMAIN:
        return []
    except dns.resolver.NoAnswer:
        return []
    except Exception as e:  # timeout, servfail, no nameservers
        logger.info(f"TXT lookup {name} failed: {type(e).__name__}")
        return []
    out = []
    for rdata in answers:
        parts = getattr(rdata, "strings", None) or []
        out.append(b"".join(parts).decode("utf-8", "replace")
                   if parts else str(rdata).strip('"'))
    return out


def _mx_sync(name: str) -> List[Tuple[int, str]]:
    import dns.resolver
    try:
        answers = _resolver().resolve(name, "MX")
    except dns.resolver.NXDOMAIN:
        return []
    except dns.resolver.NoAnswer:
        return []
    except Exception as e:
        logger.info(f"MX lookup {name} failed: {type(e).__name__}")
        return []
    return [(int(r.preference), str(r.exchange).rstrip(".")) for r in answers]


def _ns_sync(domain: str) -> List[str]:
    """Nameservers for the domain, walking up one label when the exact
    name has none (a `mail.studiok.com` sending domain still lives in
    studiok.com's zone)."""
    import dns.resolver
    labels = (domain or "").strip(".").split(".")
    candidates = [".".join(labels[i:]) for i in range(0, max(1, len(labels) - 1))]
    for cand in candidates:
        try:
            answers = _resolver().resolve(cand, "NS")
            return [str(r.target).rstrip(".") for r in answers]
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except Exception as e:
            logger.info(f"NS lookup {cand} failed: {type(e).__name__}")
            return []
    return []


async def _in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


async def lookup_txt(name: str) -> List[str]:
    return await _in_thread(_txt_sync, name)


async def lookup_mx(name: str) -> List[Tuple[int, str]]:
    return await _in_thread(_mx_sync, name)


async def lookup_ns(domain: str) -> List[str]:
    return await _in_thread(_ns_sync, domain)


async def check_records(domain: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve every record concurrently and attach a verdict to each.

    Returns {records: [...with `fqdn` and `dns`], provider, checked_at,
    required_ok, all_ok}. `required_ok` ignores optional rows (DMARC), so
    the caller can say "everything Resend needs is in place" separately
    from "and the recommended extra is too"."""
    recs = [dict(r) for r in (records or []) if isinstance(r, dict)]
    fqdns = [fqdn_for(r.get("name"), domain) for r in recs]

    async def _one(rec: Dict[str, Any], host: str):
        if (rec.get("type") or "").upper() == "MX":
            return [], await lookup_mx(host)
        return await lookup_txt(host), []

    results = await asyncio.gather(
        *[_one(r, h) for r, h in zip(recs, fqdns)],
        lookup_ns(domain),
        return_exceptions=True)
    ns_result = results[-1]
    nameservers = ns_result if isinstance(ns_result, list) else []

    out: List[Dict[str, Any]] = []
    required_ok = True
    all_ok = True
    for rec, host, res in zip(recs, fqdns, results[:-1]):
        if isinstance(res, Exception):
            found_txt, found_mx = [], []
        else:
            found_txt, found_mx = res
        verdict = evaluate_record(rec, found_txt, found_mx)
        row = {**rec, "fqdn": host, "dns": verdict}
        out.append(row)
        if not verdict["match"]:
            all_ok = False
            if not rec.get("optional"):
                required_ok = False

    return {
        "records": out,
        "provider": detect_provider(nameservers),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "required_ok": required_ok,
        "all_ok": all_ok,
    }
