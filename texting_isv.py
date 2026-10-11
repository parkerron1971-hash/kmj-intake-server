"""texting_isv.py — Twilio's side of texting under each business's own name.

docs/plans/ISV_TEXTING_PLAN_2026-10-11.md, step 3 (Kevin, 2026-10-11:
"building everything now so it's setup for people to get updates and
everything through our system"; sub-account per business; the EIN comes
from where the business already keeps it). texting_registration.py owns the
row, the owner's routes and the updates; this module only talks to Twilio,
following Twilio's ISV API guide (onboarding-isv-api, Standard and
Low-Volume Standard brands) step by step:

  0. A SUB-ACCOUNT for the business (Kevin's decision D3), named with the
     business id so it can always be found again. Every call below is made
     AS that sub-account ("use the Account SID and Auth Token for the Account
     your customer will use"); its token is read from Twilio with ours and
     kept in memory only.
  1. The SECONDARY CUSTOMER PROFILE: the business information (legal name,
     type, industry, EIN, website), the authorized representative, the
     address, assigned to our primary profile, checked by Twilio's own
     evaluation, then submitted for review.
  2. The A2P TRUST PRODUCT (company type), with the profile attached,
     checked and submitted.
  3. The BRAND (Low-Volume Standard: secondary vetting skipped). This is the
     call that costs money (about $4.50 now, $15 when the campaign is vetted).
  4. The MESSAGING SERVICE the business's texts will go through, pointed at
     our inbound and delivery webhooks.
  5. The CAMPAIGN (Low Volume Mixed), only once Twilio approves the brand,
     with the exact words the owner saw when they sent it.

Every step is safe to run again. A step that already happened is found (its
id saved on the registration, or found in the business's own sub-account,
which holds nothing else) and skipped, so a crash, a deploy or a retry can
never register a business twice or pay twice.

Plain HTTP, the requests Twilio's guide shows, so what is sent is exactly
what the guide documents. Blocking: call through asyncio.to_thread.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("texting_isv")

API = "https://api.twilio.com/2010-04-01"
TRUSTHUB = "https://trusthub.twilio.com/v1"
MESSAGING = "https://messaging.twilio.com/v1"

PROFILE_POLICY = "RNdfbf3fae0e1107f8aded0e7cead80bf5"   # Secondary Customer Profile
A2P_POLICY = "RNb0d4771c2c98518d916a3d4cd70a8f8b"       # A2P messaging trust product
# Our approved primary customer profile (The Solutionist System LLC). Not a
# secret; the env var lets a test account point elsewhere.
PRIMARY_PROFILE_SID = "BUf7450203af9b02e67766ef6403943c37"

USE_CASE = "LOW_VOLUME"   # Twilio's "Low Volume Mixed"

# Our answers' business types → Twilio's allowed values (sole proprietors
# register on Twilio's separate Sole Proprietor path).
TWILIO_BUSINESS_TYPES = {"llc": "Limited Liability Corporation", "corporation": "Corporation",
                         "partnership": "Partnership", "nonprofit": "Non-profit Corporation"}

# Twilio's industries, in the owner's words. A nonprofit is always
# NOT_FOR_PROFIT (Twilio's rule), so it is never asked.
INDUSTRIES = {
    "PROFESSIONAL_SERVICES": "Professional services (coaching, consulting, creative work)",
    "CONSUMER": "Personal and consumer services (salons, barbers, fitness)",
    "HEALTHCARE": "Health and wellness",
    "RELIGION": "Faith and ministry",
    "EDUCATION": "Education and training",
    "FOOD_AND_BEVERAGE": "Food and drink",
    "RETAIL": "Retail and products",
    "HOSPITALITY": "Hospitality and events",
    "REAL_ESTATE": "Real estate",
    "LEGAL": "Legal",
    "FINANCIAL": "Finance and accounting",
    "MEDIA": "Media and entertainment",
    "TECHNOLOGY": "Technology",
    "CONSTRUCTION": "Construction and home services",
    "AUTOMOTIVE": "Automotive",
    "TRANSPORTATION": "Transportation and delivery",
}

TIMEOUT = 20.0


class TwilioDown(Exception):
    """Twilio couldn't be reached or answered 5xx: try again later, nothing is
    wrong with the business's details."""


class TwilioRefused(Exception):
    """Twilio answered 4xx. `code` and `message` are Twilio's."""

    def __init__(self, status: int, code: Any, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class NeedsFix(Exception):
    """Twilio's own check found something in the business's details. `reasons`
    are Twilio's words, one per problem, to show the owner."""

    def __init__(self, reasons: List[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# ── talking to Twilio ─────────────────────────────────────────────────

class Api:
    """One Twilio account's credentials. Requests are form posts and JSON
    reads, exactly as in Twilio's guide."""

    def __init__(self, sid: str, token: str):
        self.sid, self._token = sid, token

    def _send(self, method: str, url: str, *, data: Any = None, params: Any = None,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        try:
            r = _http(method, url, auth=(self.sid, self._token), data=data, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise TwilioDown(f"{method} {_short(url)}: {e}") from None
        if r.status_code >= 500:
            raise TwilioDown(f"{method} {_short(url)}: {r.status_code}")
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        if r.status_code >= 400:
            raise TwilioRefused(r.status_code, body.get("code"), str(body.get("message") or r.text[:300]))
        return body

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._send("GET", url, params=params)

    def post(self, url: str, data: Any, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._send("POST", url, data=data, headers=headers)


def _http(method: str, url: str, **kw: Any) -> httpx.Response:
    """The one network call (tests replace it)."""
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.request(method, url, **kw)


def _short(url: str) -> str:
    return re.sub(r"^https://[^/]+", "", url).split("?")[0]


def _env(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if not val:
        raise RuntimeError(f"Texting registration isn't configured: {name} is missing")
    return val


def parent() -> Api:
    """Our main account. The ACCOUNT auth token (not the send-only API key):
    creating sub-accounts and reading their tokens needs it."""
    return Api(_env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"))


def primary_profile_sid() -> str:
    return (os.environ.get("TWILIO_PRIMARY_PROFILE_SID") or PRIMARY_PROFILE_SID).strip()


def isv_email() -> str:
    """Where Twilio emails status changes. Twilio: an address the ISV owns,
    never the business's."""
    return (os.environ.get("TWILIO_ISV_EMAIL") or os.environ.get("PLATFORM_OWNER_EMAIL") or "").strip() \
        or _env("TWILIO_ISV_EMAIL")


def webhook_base() -> str:
    return (os.environ.get("SMS_WEBHOOK_BASE") or "https://kmj-intake-server-production.up.railway.app").rstrip("/")


_SUB_TOKENS: Dict[str, str] = {}


def sub_api(account_sid: str) -> Api:
    """The business's sub-account. Its token is read from Twilio with ours
    and kept in memory only, never stored."""
    token = _SUB_TOKENS.get(account_sid)
    if not token:
        acct = parent().get(f"{API}/Accounts/{account_sid}.json")
        token = str(acct.get("auth_token") or "")
        if not token:
            raise TwilioDown("the sub-account's token couldn't be read")
        _SUB_TOKENS[account_sid] = token
    return Api(account_sid, token)


def account_name(business_id: str) -> str:
    """The sub-account's name: the business id, so it is always found again."""
    return f"Solutionist business {business_id}"


# ── what Twilio is told ───────────────────────────────────────────────

def ein_dashed(ein: str) -> str:
    digits = re.sub(r"\D", "", ein or "")
    if len(digits) != 9:
        raise NeedsFix(["The EIN should be nine digits, like 12-3456789."])
    return f"{digits[:2]}-{digits[2:]}"


def job_position(title: str) -> str:
    """Twilio's fixed list, from the title the owner typed."""
    t = (title or "").lower()
    if re.search(r"\b(ceo|owner|founder|co-founder|president|principal|proprietor|pastor)\b", t):
        return "CEO"
    if re.search(r"\b(cfo|treasurer)\b", t):
        return "CFO"
    if re.search(r"\b(vp|vice president)\b", t):
        return "VP"
    if re.search(r"\bdirector\b", t):
        return "Director"
    if re.search(r"\b(gm|general manager|manager)\b", t):
        return "GM"
    if re.search(r"\bcounsel\b", t):
        return "General Counsel"
    return "Other"


def industry_for(answers: Dict[str, Any]) -> str:
    if answers.get("business_type") == "nonprofit":
        return "NOT_FOR_PROFIT"
    ind = answers.get("industry")
    if ind not in INDUSTRIES:
        raise NeedsFix(["Choose the industry closest to the business."])
    return str(ind)


def business_information(answers: Dict[str, Any], *, ein: str, website: str) -> Dict[str, Any]:
    btype = TWILIO_BUSINESS_TYPES.get(str(answers.get("business_type")))
    if not btype:
        raise NeedsFix(["Registration with an EIN is for LLCs, corporations, partnerships and nonprofits."])
    return {
        "business_name": answers["legal_name"],
        "business_identity": "direct_customer",   # the business itself; we are the ISV
        "business_type": btype,
        "business_industry": industry_for(answers),
        "business_registration_identifier": "EIN",
        "business_registration_number": ein_dashed(ein),
        "business_regions_of_operation": "USA_AND_CANADA",
        "website_url": website,
    }


def representative(answers: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "first_name": answers["rep_first_name"], "last_name": answers["rep_last_name"],
        "email": answers["rep_email"], "phone_number": answers["rep_phone"],
        "business_title": answers["rep_title"], "job_position": job_position(answers.get("rep_title") or ""),
    }


def address(answers: Dict[str, Any]) -> Dict[str, Any]:
    return {"CustomerName": answers["legal_name"], "Street": answers["street"], "City": answers["city"],
            "Region": answers["state"], "PostalCode": answers["postal_code"], "IsoCountry": "US"}


def company_type(answers: Dict[str, Any]) -> str:
    return "non-profit" if answers.get("business_type") == "nonprofit" else "private"


def campaign_form(words: Dict[str, Any], brand_sid: str) -> List[Tuple[str, str]]:
    """The campaign request: Twilio's guide, 5.2 and 5.3. Samples are
    repeated keys. Keyword handling is Twilio's default (STOP, START, HELP),
    so no keyword fields."""
    form: List[Tuple[str, str]] = [
        ("BrandRegistrationSid", brand_sid),
        ("UsAppToPersonUsecase", words.get("use_case") or USE_CASE),
        ("Description", words["description"]),
        ("MessageFlow", words["message_flow"]),
        ("HasEmbeddedLinks", "true" if words.get("has_embedded_links") else "false"),
        ("HasEmbeddedPhone", "true" if words.get("has_embedded_phone") else "false"),
        ("PrivacyPolicyUrl", words["privacy_url"]),
        ("TermsAndConditionsUrl", words["terms_url"]),
    ]
    for s in list(words.get("samples") or [])[:5]:
        form.append(("MessageSamples", s))
    return form


def _reasons(evaluation: Dict[str, Any]) -> List[str]:
    """Twilio's evaluation, as a list of its own sentences."""
    out: List[str] = []
    for res in evaluation.get("results") or []:
        if res.get("passed"):
            continue
        for bad in res.get("invalid") or []:
            if bad.get("failure_reason"):
                out.append(str(bad["failure_reason"]))
        if not res.get("invalid") and res.get("failure_reason"):
            out.append(str(res["failure_reason"]))
    return list(dict.fromkeys(out))[:6] or ["Twilio's check didn't pass, and it didn't say why."]


def _errors(obj: Dict[str, Any]) -> List[str]:
    """A rejection's reasons from a brand, campaign or profile."""
    out: List[str] = []
    for e in obj.get("errors") or []:
        if isinstance(e, dict):
            text = e.get("description") or e.get("message") or e.get("error_message")
            if text:
                out.append(str(text))
        elif e:
            out.append(str(e))
    if obj.get("failure_reason"):
        out.append(str(obj["failure_reason"]))
    return list(dict.fromkeys(out))[:6]


# ── sending it (idempotent, step by step) ─────────────────────────────

Save = Callable[[Dict[str, Any]], None]


def _find(api: Api, url: str, key: str, match: Callable[[Dict[str, Any]], bool],
          params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The first listed resource that matches, or None."""
    page = api.get(url, params={"PageSize": 50, **(params or {})})
    for row in page.get(key) or []:
        if match(row):
            return row
    return None


def _attach(api: Api, url: str, object_sid: str) -> None:
    """Attach, treating "already attached" as done (a retry after a crash)."""
    try:
        api.post(url, {"ObjectSid": object_sid})
    except TwilioRefused as e:
        if "already" in e.message.lower() or "duplicate" in e.message.lower():
            return
        raise


def _end_user(api: Api, t: Dict[str, Any], key: str, kind: str, name: str,
              attributes: Dict[str, Any], save: Save) -> str:
    """Create the EndUser, or bring a saved one up to date (the owner fixed
    something after Twilio's check)."""
    sid = t.get(key)
    if sid:
        api.post(f"{TRUSTHUB}/EndUsers/{sid}", {"Attributes": json.dumps(attributes)})
        return str(sid)
    made = api.post(f"{TRUSTHUB}/EndUsers", {"Type": kind, "FriendlyName": name[:64],
                                             "Attributes": json.dumps(attributes)})
    t[key] = made["sid"]
    save(t)
    return str(made["sid"])


def ensure_account(t: Dict[str, Any], business_id: str, save: Save) -> Api:
    """Step 0: the business's sub-account."""
    if not t.get("account_sid"):
        p = parent()
        name = account_name(business_id)
        found = _find(p, f"{API}/Accounts.json", "accounts", lambda a: a.get("friendly_name") == name
                      and a.get("status") != "closed", params={"FriendlyName": name})
        acct = found or p.post(f"{API}/Accounts.json", {"FriendlyName": name})
        t["account_sid"] = acct["sid"]
        save(t)
    return sub_api(str(t["account_sid"]))


def ensure_profile(api: Api, t: Dict[str, Any], answers: Dict[str, Any], *, ein: str, website: str,
                   callback: str, save: Save) -> None:
    """Step 1: the Secondary Customer Profile, checked and submitted."""
    legal = answers["legal_name"]
    if not t.get("profile_sid"):
        found = _find(api, f"{TRUSTHUB}/CustomerProfiles", "results",
                      lambda p: p.get("policy_sid") == PROFILE_POLICY)
        made = found or api.post(f"{TRUSTHUB}/CustomerProfiles", {
            "PolicySid": PROFILE_POLICY, "FriendlyName": f"{legal} secondary profile"[:64],
            "Email": isv_email(), "StatusCallback": callback})
        t["profile_sid"] = made["sid"]
        save(t)
    bu = str(t["profile_sid"])
    if t.get("profile_submitted"):
        return
    assign = f"{TRUSTHUB}/CustomerProfiles/{bu}/EntityAssignments"
    biz = _end_user(api, t, "business_end_user", "customer_profile_business_information",
                    f"{legal} business information", business_information(answers, ein=ein, website=website), save)
    rep = _end_user(api, t, "rep_end_user", "authorized_representative_1", f"{legal} authorized rep",
                    representative(answers), save)
    if t.get("address_sid"):
        api.post(f"{API}/Accounts/{api.sid}/Addresses/{t['address_sid']}.json",
                 {k: v for k, v in address(answers).items() if k != "IsoCountry"})
    else:
        made = api.post(f"{API}/Accounts/{api.sid}/Addresses.json", {"FriendlyName": f"{legal} address"[:64],
                                                                      **address(answers)})
        t["address_sid"] = made["sid"]
        save(t)
    if not t.get("address_document"):
        doc = api.post(f"{TRUSTHUB}/SupportingDocuments", {
            "Type": "customer_profile_address", "FriendlyName": f"{legal} address document"[:64],
            "Attributes": json.dumps({"address_sids": t["address_sid"]})})
        t["address_document"] = doc["sid"]
        save(t)
    if not t.get("profile_assigned"):
        for sid in (biz, rep, str(t["address_document"]), primary_profile_sid()):
            _attach(api, assign, sid)
        t["profile_assigned"] = True
        save(t)
    ev = api.post(f"{TRUSTHUB}/CustomerProfiles/{bu}/Evaluations", {"PolicySid": PROFILE_POLICY})
    if ev.get("status") != "compliant":
        raise NeedsFix(_reasons(ev))
    api.post(f"{TRUSTHUB}/CustomerProfiles/{bu}", {"Status": "pending-review"})
    t["profile_submitted"] = True
    save(t)


def ensure_trust_product(api: Api, t: Dict[str, Any], answers: Dict[str, Any], *, callback: str,
                         save: Save) -> None:
    """Step 2: the A2P trust product, checked and submitted."""
    legal = answers["legal_name"]
    if not t.get("trust_sid"):
        found = _find(api, f"{TRUSTHUB}/TrustProducts", "results", lambda p: p.get("policy_sid") == A2P_POLICY)
        made = found or api.post(f"{TRUSTHUB}/TrustProducts", {
            "PolicySid": A2P_POLICY, "FriendlyName": f"{legal} A2P trust product"[:64],
            "Email": isv_email(), "StatusCallback": callback})
        t["trust_sid"] = made["sid"]
        save(t)
    bu = str(t["trust_sid"])
    if t.get("trust_submitted"):
        return
    info = _end_user(api, t, "messaging_end_user", "us_a2p_messaging_profile_information",
                     f"{legal} messaging profile", {"company_type": company_type(answers)}, save)
    if not t.get("trust_assigned"):
        for sid in (info, str(t["profile_sid"])):
            _attach(api, f"{TRUSTHUB}/TrustProducts/{bu}/EntityAssignments", sid)
        t["trust_assigned"] = True
        save(t)
    ev = api.post(f"{TRUSTHUB}/TrustProducts/{bu}/Evaluations", {"PolicySid": A2P_POLICY})
    if ev.get("status") != "compliant":
        raise NeedsFix(_reasons(ev))
    api.post(f"{TRUSTHUB}/TrustProducts/{bu}", {"Status": "pending-review"})
    t["trust_submitted"] = True
    save(t)


def ensure_brand(api: Api, t: Dict[str, Any], save: Save) -> None:
    """Step 3: the brand. COSTS MONEY, so an existing brand in the business's
    sub-account is always reused, never doubled."""
    if t.get("brand_sid"):
        return
    found = _find(api, f"{MESSAGING}/a2p/BrandRegistrations", "data", lambda b: b.get("status") != "DELETED")
    if not found:
        time.sleep(1)   # Twilio: one brand/campaign request a second
    made = found or api.post(f"{MESSAGING}/a2p/BrandRegistrations", {
        "CustomerProfileBundleSid": t["profile_sid"], "A2PProfileBundleSid": t["trust_sid"],
        "SkipAutomaticSecVet": "true"})
    t["brand_sid"] = made["sid"]
    save(t)


def ensure_service(api: Api, t: Dict[str, Any], name: str, save: Save) -> None:
    """Step 4: the Messaging Service the business's texts go through."""
    if t.get("service_sid"):
        return
    friendly = f"{name} texting"[:64]
    found = _find(api, f"{MESSAGING}/Services", "services", lambda s: s.get("friendly_name") == friendly)
    base = webhook_base()
    made = found or api.post(f"{MESSAGING}/Services", {
        "FriendlyName": friendly, "InboundRequestUrl": f"{base}/webhooks/twilio/sms",
        "StatusCallback": f"{base}/webhooks/twilio/status"})
    t["service_sid"] = made["sid"]
    save(t)


def send(t: Dict[str, Any], *, business_id: str, name: str, answers: Dict[str, Any], ein: str,
         website: str, callback: str, save: Save) -> Dict[str, Any]:
    """Steps 0 to 4. Returns the registration's Twilio ids. Raises NeedsFix
    (the owner fixes their details), TwilioRefused or TwilioDown."""
    api = ensure_account(t, business_id, save)
    ensure_profile(api, t, answers, ein=ein, website=website, callback=callback, save=save)
    ensure_trust_product(api, t, answers, callback=callback, save=save)
    ensure_brand(api, t, save)
    ensure_service(api, t, name, save)
    return t


# ── where it stands (the sweep and Twilio's status pings) ─────────────

def check(t: Dict[str, Any], save: Save) -> Dict[str, Any]:
    """Where the registration stands, from Twilio itself, moving it along when
    it can (the campaign goes in once the brand is approved). Returns
    {stage: 'brand'|'campaign'|'approved'|'failed', reasons: [...]}."""
    api = sub_api(str(t["account_sid"]))
    for key, url in (("profile_sid", f"{TRUSTHUB}/CustomerProfiles"), ("trust_sid", f"{TRUSTHUB}/TrustProducts")):
        if t.get(key):
            bundle = api.get(f"{url}/{t[key]}")
            if bundle.get("status") == "twilio-rejected":
                return {"stage": "failed", "reasons": _errors(bundle) or ["Twilio didn't approve the business details."]}
    brand = api.get(f"{MESSAGING}/a2p/BrandRegistrations/{t['brand_sid']}")
    b = str(brand.get("status") or "").upper()
    if b in ("FAILED", "SUSPENDED", "DELETED"):
        return {"stage": "failed", "reasons": _errors(brand) or ["The carriers' registry didn't verify the business."]}
    if b != "APPROVED":
        return {"stage": "brand", "reasons": []}
    if not t.get("campaign_sid"):
        mg = str(t["service_sid"])
        found = _find(api, f"{MESSAGING}/Services/{mg}/Compliance/Usa2p", "compliance", lambda c: True)
        if not found:
            time.sleep(1)
        made = found or api.post(f"{MESSAGING}/Services/{mg}/Compliance/Usa2p",
                                 campaign_form(t["campaign_words"], str(t["brand_sid"])),
                                 headers={"X-Twilio-Api-Version": "v1.2"})
        t["campaign_sid"] = made["sid"]
        save(t)
        return {"stage": "campaign", "reasons": []}
    camp = api.get(f"{MESSAGING}/Services/{t['service_sid']}/Compliance/Usa2p/{t['campaign_sid']}")
    c = str(camp.get("campaign_status") or "").upper()
    if c == "VERIFIED":
        return {"stage": "approved", "reasons": []}
    if c in ("FAILED", "SUSPENDED"):
        return {"stage": "failed", "reasons": _errors(camp) or ["The carriers didn't approve how the business texts."]}
    return {"stage": "campaign", "reasons": []}
