from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def parse_feed(raw: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        logger.warning("rss: failed to parse XML (%s)", exc)
        return []

    _strip_namespaces(root)

    items = root.findall(".//item")
    if items:
        return [_parse_rss_item(it) for it in items]

    entries = root.findall(".//entry")
    if entries:
        return [_parse_atom_entry(e) for e in entries]

    logger.warning("rss: feed had no <item> or <entry> elements")
    return []


def _parse_rss_item(item: ET.Element) -> dict[str, Any]:
    return {
        "title":     _text(item, "title"),
        "link":      _text(item, "link"),
        "summary":   _text(item, "description") or _text(item, "content:encoded"),
        "author":    _text(item, "author") or _text(item, "dc:creator"),
        "published": _text(item, "pubDate") or _text(item, "dc:date"),
        "tags":      [c.text for c in item.findall("category") if c.text],
    }


def _parse_atom_entry(entry: ET.Element) -> dict[str, Any]:
    link_el = entry.find("link")
    link = link_el.get("href", "") if link_el is not None else ""

    author = ""
    author_el = entry.find("author")
    if author_el is not None:
        name_el = author_el.find("name")
        author = name_el.text if name_el is not None and name_el.text else ""

    return {
        "title":     _text(entry, "title"),
        "link":      link,
        "summary":   _text(entry, "summary") or _text(entry, "content"),
        "author":    author,
        "published": _text(entry, "published") or _text(entry, "updated"),
        "tags":      [c.get("term", "") for c in entry.findall("category")],
    }


def _text(parent: ET.Element, tag: str) -> str:
    local = tag.split(":")[-1]
    el = parent.find(local)
    if el is None or el.text is None:
        return ""
    return el.text


def _strip_namespaces(element: ET.Element) -> None:
    for el in element.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
