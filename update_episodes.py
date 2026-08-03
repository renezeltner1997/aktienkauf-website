#!/usr/bin/env python3
"""
Aktualisiert die "Aktuelle Folgen"-Karten in index.html anhand des Spotify/Anchor
RSS-Feeds von aktien.kauf. Gedacht zum wöchentlichen Ausführen via GitHub Actions.

Ersetzt ausschliesslich den Inhalt zwischen den Markern
<!-- EPISODES:START --> ... <!-- EPISODES:END -->
in index.html mit den 3 neuesten Episoden aus dem RSS-Feed.
"""
import re
import sys
import html
import urllib.request
from datetime import datetime
from xml.etree import ElementTree as ET

RSS_URL = "https://anchor.fm/s/10471638/podcast/rss"
INDEX_HTML = "index.html"
START_MARKER = "<!-- EPISODES:START -->"
END_MARKER = "<!-- EPISODES:END -->"
NUM_EPISODES = 3

MONTHS_DE = {
    1: "Jan", 2: "Feb", 3: "Mär", 4: "Apr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Dez",
}


def fetch_rss(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (aktienkauf-website-bot)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_snippet(description_html, max_len=170, min_len=80):
    """Find the first substantial, non-promotional paragraph for the card teaser.

    Short bold headline paragraphs (stats/teasers) are skipped in favor of the
    first real descriptive paragraph, since those make better card copy.
    """
    paragraphs = re.findall(r"<p>(.*?)</p>", description_html, flags=re.DOTALL)
    # Keyword markers checked against the cleaned text (safe: near-exclusive to ad blurbs)
    text_skip_markers = ("rabatt", "werbung", "depotwechsel", "disclaimer")
    # Ad-link domains checked against the raw (un-stripped) paragraph HTML
    href_skip_markers = ("parqet.com", "consorsbank.de", "abilitato.de")

    def is_ad_paragraph(raw, clean):
        low_clean = clean.lower()
        low_raw = raw.lower()
        return (any(m in low_clean for m in text_skip_markers)
                or any(m in low_raw for m in href_skip_markers))

    def clean_and_trim(raw):
        clean = strip_tags(raw)
        if len(clean) > max_len:
            clean = clean[:max_len].rsplit(" ", 1)[0] + "…"
        return clean

    candidates = []
    for p in paragraphs:
        clean = strip_tags(p)
        if len(clean) < 40 or is_ad_paragraph(p, clean):
            continue
        candidates.append((clean, p))

    for clean, p in candidates:
        if len(clean) >= min_len:
            return clean_and_trim(p)

    if candidates:
        return clean_and_trim(candidates[0][1])

    clean = strip_tags(description_html)
    return (clean[:max_len].rsplit(" ", 1)[0] + "…") if len(clean) > max_len else clean


def guess_category(title):
    """Uses the ORIGINAL (not lowercased) title so capitalization gives real signal
    and avoids false positives like 'ETF' matching inside 'netflix'."""
    if re.search(r"\bETFs?\b", title):
        return "ETF-Vergleich"
    # "... – mit Vorname Nachname" style guest features
    if re.search(r"\bmit\s+[A-ZÄÖÜ][\wäöüß]+\s+[A-ZÄÖÜ][\wäöüß]+", title):
        return "Interview"
    # Titles starting with "Vorname Nachname: ..." (Q&A / guest format)
    if re.match(r"^[A-ZÄÖÜ][\wäöüß]+\s+[A-ZÄÖÜ][\wäöüß]+\s*:", title):
        return "Interview"
    return "Aktienanalyse"


def format_duration(itunes_duration):
    parts = [int(p) for p in itunes_duration.strip().split(":")]
    if len(parts) == 3:
        h, m, s = parts
        total_min = h * 60 + m + (1 if s >= 30 else 0)
    elif len(parts) == 2:
        m, s = parts
        total_min = m + (1 if s >= 30 else 0)
    else:
        total_min = parts[0] // 60
    return f"{total_min} Min"


def build_card(item_el, ns):
    title = strip_tags(item_el.findtext("title") or "")
    link = (item_el.findtext("link") or "").strip()
    duration_raw = item_el.findtext("itunes:duration", namespaces=ns) or "0:00"
    description = item_el.findtext("description") or ""

    duration = format_duration(duration_raw)
    category = guess_category(title)
    snippet = extract_snippet(description)

    title_esc = html.escape(title, quote=False)
    snippet_esc = html.escape(snippet, quote=False)
    link_esc = html.escape(link, quote=True)

    return f"""      <div class="ep-card">
        <div class="ep-meta"><span>{duration}</span><span>·</span><span>{category}</span></div>
        <h4>{title_esc}</h4>
        <p>{snippet_esc}</p>
        <a class="ep-link" href="{link_esc}" target="_blank">Jetzt anhören →</a>
      </div>"""


def main():
    print(f"Fetching RSS feed from {RSS_URL} ...")
    raw = fetch_rss(RSS_URL)
    root = ET.fromstring(raw)
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

    items = root.findall("./channel/item")[:NUM_EPISODES]
    if not items:
        print("No episodes found in feed, aborting without changes.")
        sys.exit(0)

    cards = [build_card(item, ns) for item in items]
    new_block = "\n".join(cards)

    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html_content = f.read()

    if START_MARKER not in html_content or END_MARKER not in html_content:
        print("Marker comments not found in index.html — aborting to avoid corrupting the file.")
        sys.exit(1)

    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), flags=re.DOTALL)
    replacement = f"{START_MARKER}\n{new_block}\n      {END_MARKER}"
    updated_html = pattern.sub(replacement, html_content, count=1)

    if updated_html == html_content:
        print("No changes detected — episodes are already up to date.")
        return

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print(f"Updated {INDEX_HTML} with {len(items)} latest episodes:")
    for item in items:
        print(" -", strip_tags(item.findtext("title") or ""))


if __name__ == "__main__":
    main()
