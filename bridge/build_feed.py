#!/usr/bin/env python3
"""
Fetch RSS/Atom sources listed in feeds.yaml and write a single merged Atom feed
to public/feeds/merged.xml (for GitHub Pages + Miniflux subscription).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml
from html import unescape as html_unescape
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "bridge" / "feeds.yaml"
OUT_DIR = ROOT / "public" / "feeds"
OUT_PATH = OUT_DIR / "merged.xml"
MAX_ENTRIES = 400
USER_AGENT = "rss-bridge/1.0 (+https://github.com/pages)"


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_url(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def entry_datetime(entry: feedparser.FeedParserDict) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                dt = date_parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError):
                continue
    return datetime.now(timezone.utc)


def entry_id(entry: feedparser.FeedParserDict, source_name: str) -> str:
    if entry.get("id"):
        return str(entry.id)
    if entry.get("link"):
        return str(entry.link)
    h = hashlib.sha256(
        json.dumps(
            [source_name, entry.get("title", ""), entry.get("link", ""), entry.get("summary", "")],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return f"urn:bridge:sha256:{h}"


def plain_summary(entry: feedparser.FeedParserDict) -> str:
    if entry.get("content"):
        parts = []
        for c in entry.content:
            if isinstance(c, dict) and c.get("value"):
                parts.append(c["value"])
        if parts:
            return "\n".join(parts)
    if entry.get("summary"):
        return str(entry.summary)
    if entry.get("description"):
        return str(entry.description)
    return ""


def to_plain_text(html_or_text: str, max_len: int = 20000) -> str:
    t = re.sub(r"<[^>]+>", " ", html_or_text)
    t = html_unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        log(f"Missing config: {CONFIG_PATH}")
        sys.exit(1)
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    config = load_config()
    meta = config.get("feed") or {}
    title = meta.get("title") or "Bridge (merged)"
    subtitle = meta.get("subtitle") or ""
    self_url = meta.get("self_url") or "tag:bridge,2026:merged"
    sources = config.get("sources") or []

    collected: list[tuple[datetime, dict]] = []

    for src in sources:
        name = src.get("name") or "source"
        url = src.get("url")
        if not url:
            log(f"Skip source without url: {name}")
            continue
        try:
            body = fetch_url(url)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"Fetch failed [{name}] {url}: {e}")
            continue
        parsed = feedparser.parse(body)
        if parsed.bozo and not parsed.entries:
            log(f"Parse warning [{name}] {url}: {getattr(parsed, 'bozo_exception', 'unknown')}")
        for entry in parsed.entries:
            collected.append(
                (
                    entry_datetime(entry),
                    {
                        "entry": entry,
                        "source_name": name,
                    },
                )
            )
        log(f"OK [{name}] entries={len(parsed.entries)}")

    collected.sort(key=lambda x: x[0], reverse=True)
    collected = collected[:MAX_ENTRIES]

    updated = datetime.now(timezone.utc)
    if collected:
        updated = max(t for t, _ in collected)

    atom_ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("", atom_ns)

    feed_el = ET.Element(f"{{{atom_ns}}}feed")

    t_el = ET.SubElement(feed_el, f"{{{atom_ns}}}title")
    t_el.text = title

    if subtitle:
        st_el = ET.SubElement(feed_el, f"{{{atom_ns}}}subtitle")
        st_el.text = subtitle

    id_el = ET.SubElement(feed_el, f"{{{atom_ns}}}id")
    id_el.text = self_url

    upd_el = ET.SubElement(feed_el, f"{{{atom_ns}}}updated")
    upd_el.text = updated.strftime("%Y-%m-%dT%H:%M:%SZ")

    link_self = ET.SubElement(feed_el, f"{{{atom_ns}}}link")
    link_self.set("rel", "self")
    link_self.set("href", self_url)
    link_self.set("type", "application/atom+xml")

    gen = ET.SubElement(feed_el, f"{{{atom_ns}}}generator")
    gen.text = "bridge/build_feed.py"
    gen.set("uri", "https://miniflux.app/")

    for dt, wrap in collected:
        entry = wrap["entry"]
        source_name = wrap["source_name"]
        eid = entry_id(entry, source_name)

        ent = ET.SubElement(feed_el, f"{{{atom_ns}}}entry")

        eid_el = ET.SubElement(ent, f"{{{atom_ns}}}id")
        eid_el.text = eid

        title_text = entry.get("title") or "(no title)"
        et = ET.SubElement(ent, f"{{{atom_ns}}}title")
        et.set("type", "text")
        et.text = to_plain_text(title_text, max_len=500) or "(no title)"

        eu = ET.SubElement(ent, f"{{{atom_ns}}}updated")
        eu.text = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        link = entry.get("link")
        if link:
            el = ET.SubElement(ent, f"{{{atom_ns}}}link")
            el.set("href", str(link))
            el.set("rel", "alternate")

        author = ET.SubElement(ent, f"{{{atom_ns}}}author")
        an = ET.SubElement(author, f"{{{atom_ns}}}name")
        an.text = source_name

        body = plain_summary(entry)
        if body:
            summary_el = ET.SubElement(ent, f"{{{atom_ns}}}summary")
            summary_el.set("type", "text")
            summary_el.text = to_plain_text(body)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(feed_el)
    ET.indent(tree, space="  ")
    tree.write(OUT_PATH, encoding="utf-8", xml_declaration=True)
    log(f"Wrote {OUT_PATH} ({len(collected)} entries)")


if __name__ == "__main__":
    main()
