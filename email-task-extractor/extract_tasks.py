#!/usr/bin/env python3
"""Daily Email Task Extractor

Connects to Verizon/AOL inbox via IMAP, reads recently opened emails,
extracts action items via Claude API, processes reply commands (add:/done:),
updates tasks.md, and sends a daily digest email.
"""

import difflib
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

# ── Configuration ─────────────────────────────────────────────────────
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
TASKS_FILE     = os.path.join(SCRIPT_DIR, "tasks.md")

MAX_BODY_CHARS   = 3000  # Caps per-email content sent to API
MAX_EMAILS       = 50    # Max new emails processed per run
LOOKBACK_DAYS    = 3     # Lookback window for new email scan
REPLY_LOOKBACK   = 30    # Lookback window for reply command scan
FUZZY_THRESHOLD  = 0.5   # Minimum similarity score to accept a done: match


# ── Helpers ───────────────────────────────────────────────────────────────
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


def open_inbox():
    """Return an authenticated, INBOX-selected IMAP connection."""
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    status, _ = mail.select("INBOX")
    if status != "OK":
        mail.logout()
        raise RuntimeError(f"Failed to select INBOX (status: {status})")
    return mail


# ── Tasks file ────────────────────────────────────────────────────────────────
def read_current_tasks():
    """Return list of outstanding task strings (without the '- [ ] ' prefix)."""
    if not os.path.exists(TASKS_FILE):
        return []
    tasks = []
    with open(TASKS_FILE) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- [ ] "):
                tasks.append(stripped[6:])
    return tasks


def remove_task(task_text):
    """Remove the first line matching '- [ ] {task_text}' from tasks.md."""
    if not os.path.exists(TASKS_FILE):
        return
    target = f"- [ ] {task_text}\n"
    with open(TASKS_FILE) as f:
        lines = f.readlines()
    removed = False
    new_lines = []
    for line in lines:
        if not removed and line == target:
            removed = True
        else:
            new_lines.append(line)
    if removed:
        with open(TASKS_FILE, "w") as f:
            f.writelines(new_lines)


def add_manual_tasks(tasks, date_str):
    """Append manually-added tasks (from reply commands) to tasks.md."""
    with open(TASKS_FILE, "a") as f:
        f.write(f"\n## {date_str} — Added by reply\n\n")
        for task in tasks:
            f.write(f"- [ ] {task}\n")


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


# ── Fuzzy matching ────────────────────────────────────────────────────────────────
def fuzzy_match_task(query, tasks):
    """Return (best_matching_task, score) or (None, 0) if no confident match."""
    if not tasks:
        return None, 0.0
    query_lower = query.lower().strip()
    tasks_lower = [t.lower().strip() for t in tasks]
    matches = difflib.get_close_matches(query_lower, tasks_lower, n=1, cutoff=FUZZY_THRESHOLD)
    if matches:
        idx = tasks_lower.index(matches[0])
        score = difflib.SequenceMatcher(None, query_lower, matches[0]).ratio()
        return tasks[idx], score
    return None, 0.0


# ── Reply command parsing ─────────────────────────────────────────────────────────────
def parse_commands(body):
    """Extract add:/done: commands from a reply body, ignoring quoted lines."""
    adds, dones = [], []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue  # skip quoted text
        lower = stripped.lower()
        if lower.startswith("add:"):
            task = stripped[4:].strip()
            if task:
                adds.append(task)
        elif lower.startswith("done:"):
            task = stripped[5:].strip()
            if task:
                dones.append(task)
    return adds, dones


def process_reply_commands(processed_ids, today):
    """
    Scan inbox for replies to digest emails and process add:/done: commands.
    Returns a results dict summarising what was changed.
    """
    results = {"added": [], "completed": [], "unmatched": []}
    since_date = (datetime.now() - timedelta(days=REPLY_LOOKBACK)).strftime("%d-%b-%Y")

    mail = open_inbox()
    _, nums = mail.search(None, f'SUBJECT "Daily Task Digest" SINCE {since_date}')

    if not nums[0]:
        mail.logout()
        return results

    current_tasks = read_current_tasks()

    for num in nums[0].split():
        _, data = mail.fetch(num, "(RFC822)")
        if not data or not data[0]:
            continue
        msg = email.message_from_bytes(data[0][1])

        msg_id = msg.get("Message-ID", "").strip()
        if not msg_id or msg_id in processed_ids:
            continue

        subject = decode_str(msg.get("Subject", ""))
        if not subject.lower().startswith("re:"):
            continue  # ignore originals; only process replies

        body = extract_body(msg)
        adds, dones = parse_commands(body)

        for task in adds:
            results["added"].append(task)
            current_tasks.append(task)

        for query in dones:
            match, score = fuzzy_match_task(query, current_tasks)
            if match:
                remove_task(match)
                current_tasks.remove(match)
                results["completed"].append((query, match))
            else:
                results["unmatched"].append(query)

        processed_ids.add(msg_id)

    mail.logout()

    if results["added"]:
        add_manual_tasks(results["added"], today)

    return results


# ── IMAP: new email scan ──────────────────────────────────────────────────────────────
def fetch_new_opened_emails(processed_ids):
    """Return list of unprocessed emails marked Seen within the lookback window."""
    since_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    mail = open_inbox()
    _, nums = mail.search(None, f"SEEN SINCE {since_date}")

    results = []
    if not nums[0]:
        mail.logout()
        return results

    for num in nums[0].split()[-MAX_EMAILS:]:
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


# ── Digest email ───────────────────────────────────────────────────────────────
def send_digest(date_str, reply_results, new_entries):
    """Send upgraded digest: reply summary, new items, full task list, instructions."""
    sections = []

    # 1. Reply commands processed
    has_reply_activity = any(reply_results[k] for k in ("added", "completed", "unmatched"))
    if has_reply_activity:
        lines = ["── Reply Commands Processed ──"]
        for task in reply_results["added"]:
            lines.append(f"  + Added: {task}")
        for query, match in reply_results["completed"]:
            lines.append(f"  v Completed: {match}")
        for query in reply_results["unmatched"]:
            lines.append(f"  ? No match found for: '{query}' — task not removed")
        sections.append("\n".join(lines))

    # 2. New tasks from emails
    if new_entries:
        lines = ["── New Action Items Found Today ──"]
        for entry in new_entries:
            lines.append(f"\nFrom: {entry['sender']}")
            lines.append(f"Subject: {entry['subject']}")
            for task in entry["tasks"]:
                lines.append(f"  - {task}")
        sections.append("\n".join(lines))
    elif not has_reply_activity:
        sections.append("No new action items found in today's emails.")

    # 3. Full current task list
    current_tasks = read_current_tasks()
    if current_tasks:
        lines = ["── Your Full Task List ──"]
        for i, task in enumerate(current_tasks, 1):
            lines.append(f"  {i}. {task}")
        sections.append("\n".join(lines))
    else:
        sections.append("── Your Full Task List ──\n  (empty — all caught up!)")

    # 4. Instructions
    sections.append(
        "── How to update this list ──\n"
        "Reply to this email with one command per line:\n"
        "  add: your new task here\n"
        "  done: task to mark complete"
    )

    body_text = "\n\n".join(sections)

    total_outstanding = len(current_tasks)
    subject = f"Daily Task Digest {date_str} — {total_outstanding} task(s) outstanding"

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


# ── Main ────────────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Running email task extraction for {today}")

    processed_ids = load_processed_ids()
    print(f"Previously processed emails: {len(processed_ids)}")

    # Phase 1: process reply commands (add:/done:)
    print("Scanning for reply commands...")
    reply_results = process_reply_commands(processed_ids, today)
    if reply_results["added"]:
        print(f"  Added {len(reply_results['added'])} task(s) from replies")
    if reply_results["completed"]:
        print(f"  Completed {len(reply_results['completed'])} task(s) from replies")
    if reply_results["unmatched"]:
        print(f"  Unmatched done: queries: {reply_results['unmatched']}")

    # Phase 2: extract tasks from new opened emails
    print("Scanning for new opened emails...")
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

    # Phase 3: send digest
    send_digest(today, reply_results, new_entries)
    print("Done.")


if __name__ == "__main__":
    main()
