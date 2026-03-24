#!/usr/bin/env python3
"""Daily Email Task Extractor

Connects to Verizon/AOL inbox via IMAP, reads recently opened emails,
extracts action items via Claude API, updates tasks.md, and sends
a digest email to configured recipients.
"""

import imaplib
import email
import smtplib
import json
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header as _decode_header
import anthropic

# ── Configuration ─────────────────────────────────────────────────────────────
EMAIL_ADDRESS     = os.environ["VERIZON_EMAIL"]
EMAIL_PASSWORD    = os.environ["VERIZON_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

DIGEST_TO = ["mikes9@verizon.net", "mikes@recvc.com"]

IMAP_HOST = "imap.aol.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.aol.com"
SMTP_PORT = 587

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FILE = os.path.join(SCRIPT_DIR, "processed_email_ids.json")
TASKS_FILE     = os.path.join(os.path.dirname(SCRIPT_DIR), "tasks.md")

MAX_BODY_CHARS = 3000  # Caps per-email content sent to API
MAX_EMAILS     = 50    # Max emails processed per run
LOOKBACK_DAYS  = 3     # Scan emails received within this window


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


def extract_body(msg):
    """Return plain-text body of an email, truncated to MAX_BODY_CHARS."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                raw = part.get_payload(decode=True)
                if raw:
                    charset = part.get_content_charset() or "utf-8"
                    body = raw.decode(charset, errors="replace")
                    break
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            charset = msg.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
    return body[:MAX_BODY_CHARS]


def load_processed_ids():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    return set()


def save_processed_ids(ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(sorted(ids), f, indent=2)


# ── IMAP ──────────────────────────────────────────────────────────────────────
def fetch_new_opened_emails(processed_ids):
    """Return list of unprocessed emails marked Seen within the lookback window."""
    since_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    mail.select("INBOX", readonly=True)

    _, nums = mail.search(None, f"SEEN SINCE {since_date}")

    results = []
    if not nums[0]:
        mail.logout()
        return results

    # Take most recent N to cap processing time
    all_nums = nums[0].split()[-MAX_EMAILS:]

    for num in all_nums:
        _, data = mail.fetch(num, "(RFC822)")
        if not data or not data[0]:
            continue
        msg = email.message_from_bytes(data[0][1])
        msg_id = msg.get("Message-ID", "").strip()
        if not msg_id or msg_id in processed_ids:
            continue

        results.append({
            "message_id": msg_id,
            "subject":    decode_str(msg.get("Subject", "(no subject)")),
            "sender":     decode_str(msg.get("From", "")),
            "body":       extract_body(msg),
        })

    mail.logout()
    return results


# ── Claude API ────────────────────────────────────────────────────────────────
def extract_tasks_from_email(subject, sender, body):
    """Ask Claude to extract action items from one email. Returns list of strings."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are helping extract action items from emails for Mike.

Email:
From: {sender}
Subject: {subject}
Body:
{body}

Identify any action items Mike needs to take: replies required, appointments to schedule,
decisions needed, documents to review, calls to make, deadlines to meet, etc.

Respond with ONLY a JSON array of concise action item strings.
If there are no action items, respond with: []

Example: ["Reply to John about the project timeline", "Schedule dentist appointment by Friday"]"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Strip markdown code fences if model wraps output
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        items = json.loads(text)
        return [str(i) for i in items if i]
    except json.JSONDecodeError:
        return []


# ── Tasks file ────────────────────────────────────────────────────────────────
def append_to_tasks(date_str, new_entries):
    """Append today's extracted tasks to tasks.md."""
    lines = [f"\n## {date_str}\n"]
    for entry in new_entries:
        lines.append(f"**From:** {entry['sender']}  ")
        lines.append(f"**Subject:** {entry['subject']}\n")
        for task in entry["tasks"]:
            lines.append(f"- [ ] {task}")
        lines.append("")

    with open(TASKS_FILE, "a") as f:
        f.write("\n".join(lines) + "\n")


# ── Digest email ──────────────────────────────────────────────────────────────
def send_digest(date_str, new_entries):
    """Send digest email to all recipients."""
    if not new_entries:
        subject = f"Daily Task Digest {date_str} — No new action items"
        body_text = "No new action items were found in your opened emails today."
    else:
        total = sum(len(e["tasks"]) for e in new_entries)
        subject = f"Daily Task Digest {date_str} — {total} action item(s) found"
        lines = [f"Action items found in your opened emails on {date_str}:\n"]
        for entry in new_entries:
            lines.append(f"From: {entry['sender']}")
            lines.append(f"Subject: {entry['subject']}")
            for task in entry["tasks"]:
                lines.append(f"  • {task}")
            lines.append("")
        body_text = "\n".join(lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = ", ".join(DIGEST_TO)
    msg.attach(MIMEText(body_text, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, DIGEST_TO, msg.as_string())

    print(f"Digest sent to: {', '.join(DIGEST_TO)}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Running email task extraction for {today}")

    processed_ids = load_processed_ids()
    print(f"Previously processed emails: {len(processed_ids)}")

    emails = fetch_new_opened_emails(processed_ids)
    print(f"New opened emails to process: {len(emails)}")

    new_entries = []
    for em in emails:
        tasks = extract_tasks_from_email(em["subject"], em["sender"], em["body"])
        processed_ids.add(em["message_id"])

        if tasks:
            new_entries.append({
                "sender":  em["sender"],
                "subject": em["subject"],
                "tasks":   tasks,
            })
            print(f"  {len(tasks)} task(s) found in: {em['subject'][:60]}")
        else:
            print(f"  No tasks in: {em['subject'][:60]}")

    save_processed_ids(processed_ids)

    if new_entries:
        append_to_tasks(today, new_entries)
        print(f"Updated {TASKS_FILE}")

    send_digest(today, new_entries)
    print("Done.")


if __name__ == "__main__":
    main()
