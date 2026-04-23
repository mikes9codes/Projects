#!/usr/bin/env python3
"""Redan Email Bot — watches inbox for Redan emails, notifies Mike, and auto-fills the linked form."""

import imaplib
import email as email_lib
import smtplib
import json
import os
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import decode_header as _decode_header
import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
EMAIL_ADDRESS     = os.environ["VERIZON_EMAIL"]
EMAIL_PASSWORD    = os.environ["VERIZON_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

IMAP_HOST = "imap.aol.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.aol.com"
SMTP_PORT = 587

NOTIFY_EMAIL = "mikes@recvc.com"
NOTIFY_SMS   = "5163161023@vtext.com"  # Verizon SMS gateway

PROFILE = {
    "name":    "Michael Steinberg",
    "email":   "mikes@recvc.com",
    "phone":   "5163161023",
    "partner": "Zach Steinberg",
}

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FILE = os.path.join(SCRIPT_DIR, "processed_ids.json")

TARGET_SENDER  = "redan@redan.club"
TARGET_KEYWORD = "redan"
MAX_HTML_CHARS = 14_000  # chars sent to Claude per form page

# ── Helpers ───────────────────────────────────────────────────────────────────
def decode_str(value):
    if not value:
        return ""
    parts = _decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result).strip()


def extract_body_and_urls(msg):
    """Return (plain_text, html_text, [urls]) from an email message."""
    plain = ""
    html  = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = part.get("Content-Disposition", "")
            if "attachment" in disp:
                continue
            raw = part.get_payload(decode=True)
            if not raw:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            if ct == "text/plain" and not plain:
                plain = text
            elif ct == "text/html" and not html:
                html = text
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            charset = msg.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text

    url_re = re.compile(r'https?://[^\s\'"<>()\[\]]+', re.IGNORECASE)
    seen, urls = set(), []
    for src in (plain, html):
        for url in url_re.findall(src):
            url = url.rstrip(".,;:)")
            if url not in seen:
                seen.add(url)
                urls.append(url)

    return plain, html, urls


def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    return set()


def save_processed(ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(sorted(ids), f, indent=2)


# ── IMAP ──────────────────────────────────────────────────────────────────────
def fetch_target_emails(processed):
    """Return list of unprocessed emails from Redan or with 'Redan' in subject."""
    since = datetime.now().strftime("%d-%b-%Y")  # today only

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    mail.select("INBOX", readonly=True)

    _, by_sender  = mail.search(None, f'FROM "{TARGET_SENDER}" SINCE {since}')
    _, by_subject = mail.search(None, f'SUBJECT "{TARGET_KEYWORD}" SINCE {since}')

    all_nums = set()
    if by_sender[0]:
        all_nums.update(by_sender[0].split())
    if by_subject[0]:
        all_nums.update(by_subject[0].split())

    results = []
    for num in sorted(all_nums):  # oldest first
        _, data = mail.fetch(num, "(RFC822)")
        if not data or not data[0]:
            continue
        msg = email_lib.message_from_bytes(data[0][1])
        msg_id = msg.get("Message-ID", "").strip()
        if not msg_id or msg_id in processed:
            continue

        plain, html, urls = extract_body_and_urls(msg)
        results.append({
            "message_id": msg_id,
            "subject":    decode_str(msg.get("Subject", "(no subject)")),
            "sender":     decode_str(msg.get("From", "")),
            "plain":      plain,
            "urls":       urls,
        })

    mail.logout()
    return results


# ── Notify ────────────────────────────────────────────────────────────────────
def send_message(subject, body, recipients):
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = ", ".join(recipients)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.sendmail(EMAIL_ADDRESS, recipients, msg.as_string())


def send_sms(body):
    """Send SMS via Verizon @vtext.com gateway. Body must be ASCII-safe."""
    # Strip non-ASCII so the gateway doesn't reject the message
    safe = body.encode("ascii", errors="replace").decode("ascii")[:160]
    send_message("", safe, [NOTIFY_SMS])


# ── Form filler ───────────────────────────────────────────────────────────────
FILL_SYSTEM = "You are a browser-automation assistant. Return only raw JSON — no markdown, no explanation."

FILL_PROMPT = """\
Analyze this web page HTML and return a JSON array of Playwright actions to fill and submit the form on behalf of Michael Steinberg.

User profile:
  name:    Michael Steinberg
  email:   mikes@recvc.com
  phone:   5163161023
  partner/guest: Zach Steinberg (use if the form asks who they want to play with or bring)
  payment: agree to any amount proposed — check any agreement checkbox, select any payment option presented
  date/time: if the form has a date picker, choose {target_date}; for time, pick mid-morning (9–11 AM) if possible

Each action object must be one of:
  {{"action": "fill",          "selector": "CSS", "value": "TEXT"}}
  {{"action": "select_option", "selector": "CSS", "value": "VISIBLE_OPTION_TEXT"}}
  {{"action": "check",         "selector": "CSS"}}
  {{"action": "click",         "selector": "CSS"}}

Selector priority: #id > [name=x] > label-derived > tag+class
End the list with a "click" action on the submit button.
Return ONLY the JSON array.

Page HTML:
{html}
"""


def rank_urls(urls):
    """Prefer URLs that look like booking/form links."""
    keywords = ("book", "form", "sign", "register", "reserv", "join", "already", "respond", "rsvp")
    scored = []
    for url in urls:
        low = url.lower()
        score = sum(1 for kw in keywords if kw in low)
        # Penalise obvious non-form URLs
        if any(skip in low for skip in ("unsubscribe", "pixel", "track", "open.php", "click.php", "cdn-")):
            score -= 5
        scored.append((score, url))
    scored.sort(key=lambda x: -x[0])
    return [u for _, u in scored]


def fill_form(url):
    """Navigate to url, let Claude decide the fill actions, execute them. Returns status string."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    target_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        try:
            page.goto(url, timeout=30_000, wait_until="networkidle")
        except PWTimeout:
            try:
                page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            except Exception as e:
                browser.close()
                return f"Navigation failed: {e}"

        html = page.content()[:MAX_HTML_CHARS]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=FILL_SYSTEM,
            messages=[{"role": "user", "content": FILL_PROMPT.format(html=html, target_date=target_date)}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            actions = json.loads(raw)
        except json.JSONDecodeError as e:
            browser.close()
            return f"Claude returned invalid JSON ({e}). Raw: {raw[:300]}"

        errors = []
        for act in actions:
            try:
                sel = act["selector"]
                a   = act["action"]
                if a == "fill":
                    page.fill(sel, act["value"], timeout=5_000)
                elif a == "select_option":
                    page.select_option(sel, label=act["value"], timeout=5_000)
                elif a == "check":
                    page.check(sel, timeout=5_000)
                elif a == "click":
                    page.click(sel, timeout=5_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except PWTimeout:
                        pass
            except Exception as e:
                errors.append(f"{act.get('action')} {act.get('selector')}: {e}")

        final_url   = page.url
        final_title = page.title()
        browser.close()

    if errors:
        return (
            f"Completed with {len(errors)} issue(s): {'; '.join(errors[:3])}. "
            f"Final page: '{final_title}' ({final_url})"
        )
    return f"Success. Final page: '{final_title}' ({final_url})"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now_str}] Checking for Redan emails...")

    processed = load_processed()
    emails    = fetch_target_emails(processed)
    print(f"Found {len(emails)} new Redan email(s).")

    for em in emails:
        print(f"  -> {em['subject']} | from {em['sender']}")

        url_list = "\n".join(em["urls"][:10]) if em["urls"] else "(none found)"
        notify_body = (
            f"Redan email detected at {now_str}\n\n"
            f"From:    {em['sender']}\n"
            f"Subject: {em['subject']}\n\n"
            f"Links:\n{url_list}\n\n"
            f"Filling the form now..."
        )
        sms_body = f"Redan email! '{em['subject'][:60]}' - filling form now."

        try:
            send_message(f"[Bot] Redan email: {em['subject']}", notify_body, [NOTIFY_EMAIL])
            print("    Email notification sent.")
        except Exception as e:
            print(f"    Email notification failed: {e}")

        try:
            send_sms(sms_body)
            print("    SMS sent.")
        except Exception as e:
            print(f"    SMS failed: {e}")

        ranked = rank_urls(em["urls"])
        status = "No usable URLs found in email."

        for url in ranked[:4]:
            print(f"    Trying URL: {url}")
            try:
                status = fill_form(url)
                print(f"    Result: {status}")
                if "success" in status.lower() or "final page" in status.lower():
                    break
            except Exception as e:
                status = f"Exception: {e}"
                print(f"    Error: {e}")

        result_body = (
            f"Form fill result for Redan email\n\n"
            f"Subject: {em['subject']}\n"
            f"URL tried: {ranked[0] if ranked else 'N/A'}\n\n"
            f"Result: {status}"
        )
        sms_result = f"Form result: {status[:120]}"

        try:
            send_message(f"[Bot] Form result: {em['subject']}", result_body, [NOTIFY_EMAIL])
        except Exception as e:
            print(f"    Result email failed: {e}")

        try:
            send_sms(sms_result)
        except Exception as e:
            print(f"    Result SMS failed: {e}")

        processed.add(em["message_id"])

    save_processed(processed)
    print("Done.")


if __name__ == "__main__":
    main()
