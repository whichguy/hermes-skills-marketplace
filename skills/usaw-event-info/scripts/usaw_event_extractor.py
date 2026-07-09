#!/usr/bin/env python3
"""
USAW Event Page Extractor — fuzzy-matching scraper for usaweightlifting.org event pages.

Extracts structured info from any USAW national event page:
  registration links, qualifying totals, schedules, results, tickets, live stream,
  hotels, media credentials, policies, fees, deadlines, and event metadata.

Handles layout differences across events (NCW, VWS1, VWS2, Finals, Masters/Uni, WZA)
using fuzzy H3 header matching + URL pattern classification.

Layout patterns supported:
  1. Chakra UI (NCW, VWS2, Finals): H2 in one div, UL in sibling div, both inside
     a .content-tile-block container. H3 subsection headers inside each LI.
  2. Inline/paragraph (VWS1): Links in <p> and <a> tags without structured H3 sections.
  3. Mixed (Masters/Uni, WZA): Some H3 sections + some inline links.

Usage:
  uv run --with beautifulsoup4 --with requests --with rapidfuzz python usaw_event_extractor.py <URL>
  uv run --with beautifulsoup4 --with requests --with rapidfuzz python usaw_event_extractor.py <URL> --json
  uv run --with beautifulsoup4 --with requests --with rapidfuzz python usaw_event_extractor.py <URL> --markdown

Requires: beautifulsoup4, requests, rapidfuzz (installed automatically by uv).
"""

import re
import sys
import json
import argparse
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: pip install requests beautifulsoup4 rapidfuzz", file=sys.stderr)
    sys.exit(1)

from bs4 import BeautifulSoup, Tag

try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib
    class _FuzzFallback:
        @staticmethod
        def ratio(a, b):
            return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100
        @staticmethod
        def partial_ratio(a, b):
            return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100
    fuzz = _FuzzFallback()  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────────────
# Info type taxonomy — the core classification system
# ──────────────────────────────────────────────────────────────────────

INFO_TYPES: dict[str, dict] = {
    "registration": {
        "aliases": [
            "registration", "national championships registration",
            "register here", "standard registration",
        ],
        "url_patterns": [r"sport80\.com/.*(?:wizard|meets)/.*"],
        "category": "registration",
        "description": "Athlete registration links (Sport80)",
    },
    "adaptive_registration": {
        "aliases": [
            "adaptive", "adaptive national", "adaptive u25",
            "adaptive junior", "adaptive youth", "adaptive athlete",
            "adaptive athletes", "adaptive athletes -",
        ],
        "url_patterns": [r"sport80\.com/.*(?:wizard|meets)/.*"],
        "category": "registration",
        "description": "Adaptive athlete registration (Sport80)",
        "header_priority": True,
    },
    "wso_registration": {
        "aliases": [
            "mountain north wso", "mountain south wso",
            "texas-oklahoma wso", "california north wso", "ohio wso",
        ],
        "url_patterns": [r"sport80\.com/.*(?:wizard|meets)/.*"],
        "category": "registration",
        "description": "WSO championship registration (Sport80)",
        "header_priority": True,
    },
    "team_registration": {
        "aliases": ["team registration", "glen middleton", "team award"],
        "url_patterns": [r"docs\.google\.com/forms"],
        "category": "registration",
        "description": "Team registration (Google Form)",
    },
    "qualifying_totals": {
        "aliases": ["qualifying totals", "qualification totals"],
        "url_patterns": [r"qualifying-totals", r"qualifying.totals"],
        "category": "reference",
        "description": "Minimum totals required to qualify",
    },
    "event_policy": {
        "aliases": ["event policy", "rules", "policies"],
        "url_patterns": [r"governance.*rules", r"bylaws.*policies"],
        "category": "reference",
        "description": "Event rules and policies",
    },
    "edit_entry": {
        "aliases": ["edit entry", "change weight class", "how to edit"],
        "url_patterns": [r"assets\.contentstack\.io.*edit.*member", r"assets\.contentstack\.io.*infographic"],
        "category": "reference",
        "description": "How to edit entry (weight class / entry total)",
    },
    "event_guide": {
        "aliases": ["event guide", "full information", "athlete info"],
        "url_patterns": [r"canva\.com"],
        "category": "reference",
        "description": "Comprehensive event guide",
    },
    "tickets": {
        "aliases": ["tickets", "spectator", "expo tickets"],
        "url_patterns": [r"/tickets$", r"arnoldsports\.com/tickets", r"wodapalooza\.com", r"socal\.wodapalooza"],
        "category": "spectator",
        "description": "Spectator tickets",
    },
    "live_stream": {
        "aliases": ["live stream", "watch live", "watch here"],
        "url_patterns": [r"/live$", r"usaweightlifting\.org/live"],
        "category": "spectator",
        "description": "Live stream link",
    },
    "photo_packages": {
        "aliases": ["photo package", "preorder photo", "photo preorder", "lifting.life"],
        "url_patterns": [r"lifting\.life"],
        "category": "spectator",
        "description": "Photo package preorders",
    },
    "hotel": {
        "aliases": ["book a hotel", "hotel", "accommodation", "book at",
                     "book your hotel", "book today", "book here", "book through"],
        "url_patterns": [r"hilton\.com", r"marriott\.com", r"hyatt\.com", r"passkey\.com", r"book\.passkey"],
        "category": "travel",
        "description": "Hotel booking links with group codes",
    },
    "preliminary_schedule": {
        "aliases": ["preliminary schedule", "prelim schedule"],
        "url_patterns": [r"assets\.contentstack\.io.*(?:prelim|schedule)"],
        "category": "schedule",
        "description": "Preliminary competition schedule (PDF)",
        "header_priority": True,
    },
    "final_schedule": {
        "aliases": ["final schedule"],
        "url_patterns": [r"assets\.contentstack\.io.*(?:final|schedule)"],
        "category": "schedule",
        "description": "Final competition schedule (PDF)",
        "header_priority": True,
    },
    "start_list": {
        "aliases": ["start list", "entry list"],
        "url_patterns": [r"assets\.contentstack\.io.*start.?list", r"sport80\.com.*entries"],
        "category": "schedule",
        "description": "Start list / entry list",
    },
    "full_results": {
        "aliases": ["full results", "results"],  # L3 fix: removed "medal schedule" — conflicts with medal_schedule type
        "url_patterns": [r"drive\.google\.com"],
        "category": "schedule",
        "description": "Full results (Google Drive folder)",
    },
    "media_credentials": {
        "aliases": ["media credential", "media", "background check"],
        "url_patterns": [r"docs\.google\.com/forms.*media", r"quickapp\.pro",
                         r"docs\.google\.com/forms/d/[a-zA-Z0-9_-]{20,}"],
        "category": "media",
        "description": "Media credential application + background check",
        "header_priority": True,
    },
    "adaptive_athlete_info": {
        "aliases": ["adaptive athlete competition", "adaptive athlete definition",
                     "additional information on participating as an adaptive"],
        "url_patterns": [r"adaptive-athlete-competition-requirements"],
        "category": "reference",
        "description": "Adaptive athlete competition requirements",
    },
    "become_member": {
        "aliases": ["become a member", "membership", "join usaweightlifting"],
        "url_patterns": [r"/Join-USAWeightlifting"],
        "category": "reference",
        "description": "USAW membership signup",
    },
    "schedule_announcement": {
        "aliases": ["national event schedule", "usa weightlifting national event schedule"],
        "url_patterns": [r"/news/.*national-event-schedule"],
        "category": "reference",
        "description": "Annual national event schedule announcement",
    },
    "training_sites": {
        "aliases": ["alternate training", "training hall", "training site", "local clubs"],
        "url_patterns": [r"signupgenius\.com", r"maps\.app\.goo\.gl",
                         r"coloradoweightlifting", r"vardanianweightlifting", r"pinnacleweightlifting",
                         r"crossfitclintonville", r"project-lift\.org", r"steadfastbarbell",
                         r"columbusweightlifting", r"zenplanner\.com",
                         r"urldefense\.com.*(?:training|barbell|weightlifting|clintonville|steadfast|columbus|project.lift)"],
        "category": "travel",
        "description": "Alternate training sites / training hall",
    },
    "medal_schedule": {
        "aliases": ["medal schedule"],
        "url_patterns": [r"assets\.contentstack\.io.*medal"],
        "category": "schedule",
        "description": "Medal ceremony schedule (PDF)",
    },
    "helpful_links": {
        "aliases": ["visit colorado", "city of", "airport"],
        "url_patterns": [r"visitcos\.com", r"coloradosprings\.gov"],
        "category": "travel",
        "description": "Local info links (tourism, airport)",
    },
}


# ──────────────────────────────────────────────────────────────────────
# Inline metadata extraction (dates, fees, deadlines)
# ──────────────────────────────────────────────────────────────────────

DATE_TIME_PATTERNS = {
    "dates": re.compile(
        r"(?:Competition\s+)?Dates?\s*:?\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}"
        r"(?:\s*[-–—]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2})?"
        r"(?:,?\s*\d{4})?)", re.IGNORECASE),
    "venue": re.compile(r"Venue\s*:?\s*(.+?)(?:\||$)", re.IGNORECASE),
    "location": re.compile(r"Location\s*:?\s*(.+?)(?:\||$)", re.IGNORECASE),
    "qualification_period": re.compile(r"Qualification\s+Period\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "registration_opens": re.compile(r"Registration\s+Opens?\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
}

FEE_PATTERNS = {
    # L7 fix: More tolerant regex — handles "Early Bird Registration", "Early Registration",
    # "Early Bird", and variations without exact "Bird" keyword. Captures fee in optional parens.
    "early_bird": re.compile(
        r"Early\s+(?:Bird\s+)?Regist(?:er|ration)?\s*\(?(?:\$([\d,]+))\)?\s*"
        r".*?(?:Closes?\s*:??\s*)(.+?)(?:\n|$)",
        re.IGNORECASE | re.DOTALL),
    "regular": re.compile(
        r"Regular\s+Regist(?:er|ration)?\s*\(?(?:\$([\d,]+))\)?\s*"
        r".*?(?:Closes?\s*:??\s*)(.+?)(?:\n|$)",
        re.IGNORECASE | re.DOTALL),
    "late": re.compile(
        r"Late\s+Regist(?:er|ration)?\s*\(?(?:\$([\d,]+))\)?\s*"
        r".*?(?:Closes?\s*:??\s*)(.+?)(?:\n|$)",
        re.IGNORECASE | re.DOTALL),
    "flat_fee": re.compile(r"Regist(?:er|ration)?\s+(?:Cost|Fee)\s*:?\s*\$([\d,]+)", re.IGNORECASE),
}

SCHEDULE_MILESTONE_PATTERNS = {
    "preliminary_schedule_released": re.compile(
        r"Preliminary\s+Schedule\s+(?:Released|Release)\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "verification_final_entries": re.compile(
        r"Verification\s+of\s+Final\s+Entries?.*?:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "final_schedule_released": re.compile(
        r"Final\s+Schedule\s+(?:Released|Release)\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    "registration_closes": re.compile(
        r"Registration\s+Closes?\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
}


def classify_info_type(header_text: str, url: str) -> str | None:
    """Classify a link/section into an info type using fuzzy header + URL patterns.
    
    When multiple info types match the same URL pattern (e.g. preliminary_schedule
    and final_schedule both match 'assets.contentstack.io.*schedule'), the header
    text (H3) is used as a tiebreaker via fuzzy matching. Types with
    'header_priority: True' require the header to match their aliases — if the
    header doesn't match, the URL match is discarded for that type.
    """
    header_lower = (header_text or "").lower().strip()

    # URL-based classification first (most reliable)
    if url:
        url_matches = []
        for info_type, config in INFO_TYPES.items():
            for pattern in config.get("url_patterns", []):
                if re.search(pattern, url, re.IGNORECASE):
                    # If this type has header_priority, verify the header matches
                    if config.get("header_priority"):
                        # Check if header matches any alias for this type
                        # Use a higher threshold (80) for header_priority to avoid
                        # partial matches like "wso championships" matching "National Championships"
                        header_ok = False
                        if header_lower:
                            for alias in config["aliases"]:
                                if fuzz.partial_ratio(alias.lower(), header_lower) >= 80:
                                    header_ok = True
                                    break
                        if not header_ok:
                            continue  # Skip — URL matches but header doesn't confirm
                    url_matches.append(info_type)
                    break
        
        if len(url_matches) == 1:
            return url_matches[0]
        elif len(url_matches) > 1:
            # Multiple URL matches — prefer types with header_priority that passed
            priority_matches = [t for t in url_matches if INFO_TYPES[t].get("header_priority")]
            if len(priority_matches) == 1:
                return priority_matches[0]
            elif len(priority_matches) > 1:
                # Use header fuzzy matching among priority types
                candidates = priority_matches
            else:
                # No priority types — use header fuzzy matching among all
                candidates = url_matches
            
            if header_lower:
                best_match = None
                best_score: float = 0
                for itype in candidates:
                    for alias in INFO_TYPES[itype]["aliases"]:
                        score = fuzz.partial_ratio(alias.lower(), header_lower)
                        if score > best_score:
                            best_score = score
                            best_match = itype
                if best_score >= 60:
                    return best_match
            # Fall back to first match
            return url_matches[0]

    # Fuzzy header matching (when URL didn't match)
    if not header_lower:
        return None

    best_match = None
    best_score = 0.0
    threshold = 60

    for info_type, config in INFO_TYPES.items():
        for alias in config["aliases"]:
            score = fuzz.partial_ratio(alias.lower(), header_lower)
            if score > best_score:
                best_score = score
                best_match = info_type

    if best_score >= threshold:
        return best_match

    return None


def _resolve_url(href: str) -> str:
    """Resolve relative URLs to absolute."""
    if href.startswith("/"):
        return urljoin("https://www.usaweightlifting.org", href)
    return href


def _clean_link_text(text: str) -> str:
    """Clean up 'View, opens in a new tab' → 'View'."""
    return re.sub(r",?\s*opens in a new tab", "", text, flags=re.IGNORECASE).strip()


def _find_section_containers(soup: BeautifulSoup) -> list[tuple[str, Tag]]:
    """
    Find all H2 section containers on the page.
    
    USAW uses two DOM patterns:
    1. Chakra UI (NCW/VWS2/Finals): H2 and UL in sibling divs inside .content-tile-block
    2. Simpler pages: H2 followed by content in next siblings
    
    Returns list of (h2_text, container_element) pairs.
    """
    containers = []
    for h2 in soup.find_all("h2"):
        h2_text = h2.get_text(strip=True)
        # Skip permalink artifacts
        h2_text = re.sub(r"Permalink to the '([^']+)' heading", r"\1", h2_text)
        h2_text = h2_text.strip()
        if not h2_text:
            continue

        # Strategy 1: Walk up to find a common ancestor containing both H2 and a UL
        container = h2.parent
        found_ul = False
        for _ in range(5):
            if container is None:
                break
            uls = container.find_all("ul")
            if uls:
                containers.append((h2_text, container))
                found_ul = True
                break
            container = container.parent
        if not found_ul:
            # Strategy 2: Use the H2's parent as the container (no UL found)
            containers.append((h2_text, h2.parent or h2))

    return containers


def _extract_links_from_element(el: Tag, h2_section: str, seen_urls: set) -> list[dict]:
    """Extract all classified links from an element, using H3 headers as context."""
    results = []
    
    # Find all H3 headers — each is a subsection with links
    h3s = el.find_all(["h3", "h4"])
    
    if h3s:
        for h3 in h3s:
            h3_text = h3.get_text(strip=True)
            
            # Find the parent LI or containing block for this H3
            parent_li = h3.find_parent("li") or h3.find_parent(["div", "section"])
            if not parent_li:
                continue
            
            # Find links in this block
            for link in parent_li.find_all("a", href=True):
                href = str(link.get("href", ""))
                if not href or href.startswith("#"):
                    continue
                full_url = _resolve_url(href)
                if full_url in seen_urls:
                    continue
                link_text = _clean_link_text(link.get_text(strip=True))
                if _is_nav_link(full_url, link_text, h3_text):
                    continue
                seen_urls.add(full_url)
                
                info_type = classify_info_type(h3_text, full_url)
                if not info_type and link_text:
                    info_type = classify_info_type(link_text, full_url)
                
                # Check for TBA/TBD
                parent_text = parent_li.get_text(strip=True)
                tba = bool(re.search(r"\bTBA\b|\bTBD\b", parent_text, re.IGNORECASE))
                
                results.append({
                    "h2_section": h2_section,
                    "h3_header": h3_text,
                    "link_text": link_text,
                    "url": full_url,
                    "info_type": info_type,
                    "status": "TBA" if tba else "available",
                })
    
    # Also find standalone links not under any H3 (inline paragraph links)
    for link in el.find_all("a", href=True):
        href = str(link.get("href", ""))
        if not href or href.startswith("#"):
            continue
        full_url = _resolve_url(href)
        if full_url in seen_urls:
            continue
        link_text = _clean_link_text(link.get_text(strip=True))
        if _is_nav_link(full_url, link_text, ""):
            continue
        seen_urls.add(full_url)
        
        # Get surrounding text for context
        parent = link.parent
        parent_text = parent.get_text(" ", strip=True)[:200] if parent else ""
        
        info_type = classify_info_type(parent_text, full_url)
        if not info_type and link_text:
            info_type = classify_info_type(link_text, full_url)
        
        # Skip if this link is already captured by an H3 section
        # (check if it's inside an LI that has an H3)
        parent_li = link.find_parent("li")
        if parent_li and parent_li.find(["h3", "h4"]):
            continue  # Already captured above
        
        tba = bool(re.search(r"\bTBA\b|\bTBD\b", parent_text, re.IGNORECASE))
        
        results.append({
            "h2_section": h2_section,
            "h3_header": "",
            "link_text": link_text,
            "url": full_url,
            "info_type": info_type,
            "status": "TBA" if tba else "available",
        })
    
    return results


def _is_nav_link(url: str, link_text: str, h3_header: str) -> bool:
    """Filter out navigation/footer links that aren't event content."""
    nav_patterns = [
        r"/coaching", r"/weightlifting-101", r"/weightlifting-sports-performance",
        r"/elite-education", r"/youth-coach-fellowship", r"/free-courses",
        r"/online-education-courses", r"/clubs-resource-corner", r"/prior-year-event-schedules",
        r"/historical-results", r"/results$", r"/american-records",
        r"/pan-am-games-medalists", r"/olympic-team-alumni", r"/usaw-level-1", r"/usaw-level-2",
        r"/coaching/acsm", r"/coach-advancement", r"/general-liability-insurance",
        r"/referees$", r"/masters$", r"/video/playlists", r"/womens-coaching-collective",
        r"/start-a-club", r"/scholarships-and-support-services", r"/navigation/clubs",
        r"/general-education-articles", r"/givebutter\.com",
        r"usawmeetings\.chatango", r"/how-to-host-a-course", r"/how-to-run-a-meet$",
        r"usaweightliftingfoundation\.org", r"/weightlifting101",
    ]
    url_lower = url.lower()
    for pat in nav_patterns:
        if re.search(pat, url_lower):
            return True
    # Also filter Sport80 widget links (calendar widgets, not event-specific)
    if re.search(r"sport80\.com/public/widget/", url):
        return True
    if re.search(r"sport80\.com/widget/usaw_club", url):
        return True
    return False


def extract_all_links(soup: BeautifulSoup) -> list[dict]:
    """
    Extract all links from the page, grouped by H2 section and H3 subsection.
    
    Uses a robust strategy that handles multiple DOM layouts:
    1. Find H2 sections via container walk-up
    2. For each container, find H3 subsections and their links
    3. Also catch standalone links (VWS1 inline style)
    """
    sections = []
    seen_urls: set[str] = set()
    
    containers = _find_section_containers(soup)
    
    for h2_text, container in containers:
        links = _extract_links_from_element(container, h2_text, seen_urls)
        sections.extend(links)
    
    # Catch any remaining links in main content not captured by H2 sections
    main = soup.find("main") or soup.find("body")
    if main:
        for link in main.find_all("a", href=True):
            href = str(link.get("href", ""))
            if not href or href.startswith("#"):
                continue
            full_url = _resolve_url(href)
            if full_url in seen_urls:
                continue
            # Skip nav/footer links
            link_text = _clean_link_text(link.get_text(strip=True))
            if _is_nav_link(full_url, link_text, ""):
                continue
            seen_urls.add(full_url)

            parent_text = (link.parent.get_text(" ", strip=True)[:200] if link.parent else "")
            info_type = classify_info_type(parent_text, full_url)

            sections.append({
                "h2_section": "",
                "h3_header": "",
                "link_text": link_text,
                "url": full_url,
                "info_type": info_type,
                "status": "available",
            })
    
    return sections


def extract_inline_metadata(text: str) -> dict:
    """Extract dates, fees, deadlines, and milestones from page text."""
    metadata = {}
    for key, pattern in DATE_TIME_PATTERNS.items():
        m = pattern.search(text)
        if m:
            metadata[key] = m.group(1).strip()

    fees = {}
    for key, pattern in FEE_PATTERNS.items():
        m = pattern.search(text)
        if m:
            # L7 fix: Regex now captures digits only (no $ prefix). Prepend $ for display.
            fee_val = m.group(1)
            if not fee_val.startswith("$"):
                fee_val = "$" + fee_val
            if key == "flat_fee":
                fees[key] = fee_val
            else:
                fees[key] = {"fee": fee_val, "closes": m.group(2).strip()}
    if fees:
        metadata["registration_fees"] = fees

    milestones = {}
    for key, pattern in SCHEDULE_MILESTONE_PATTERNS.items():
        m = pattern.search(text)
        if m:
            milestones[key] = m.group(1).strip()
    if milestones:
        metadata["schedule_milestones"] = milestones

    return metadata


def extract_event_title_and_overview(soup: BeautifulSoup) -> dict:
    """Extract the H1 title and the date/venue/location line."""
    info = {}
    h1 = soup.find("h1")
    if h1:
        info["title"] = h1.get_text(strip=True)

    # The overview line (dates | venue | location) is in a <p> near the H1.
    # But there may be LineBreak/figure elements between them, so search forward.
    overview_text = ""
    if h1:
        for el in h1.find_all_next():
            if isinstance(el, Tag) and el.name == "p":
                text = el.get_text(" | ", strip=True)
                # The overview line contains a pipe-separated date|venue|location
                if "|" in text and re.search(r"\d{4}", text):
                    overview_text = text
                    break
            if isinstance(el, Tag) and el.name in ["h2"]:
                break  # Stop at first H2

    if overview_text:
        parts = [p.strip() for p in overview_text.split("|")]
        if len(parts) >= 1:
            info["dates_raw"] = parts[0]
        if len(parts) >= 2:
            info["venue_raw"] = parts[1]
        if len(parts) >= 3:
            info["location_raw"] = parts[2]

    return info


def classify_sport80_url(url: str) -> dict:
    """Classify a Sport80 URL and extract the meet ID."""
    info = {"url": url, "platform": "sport80"}
    
    m = re.search(r"sport80\.com/v/\d+/e/meets/(\d+)", url)
    if m:
        info["meet_id"] = m.group(1)
        info["pattern"] = "v/meets"
        return info
    
    m = re.search(r"sport80\.com/public/wizard/e/(\d+)", url)
    if m:
        info["meet_id"] = m.group(1)
        info["pattern"] = "public/wizard"
        return info
    
    m = re.search(r"sport80\.com/public/events/(\d+)/entries/(\d+)", url)
    if m:
        info["meet_id"] = m.group(1)
        info["entry_id"] = m.group(2)
        info["pattern"] = "public/events"
        return info
    
    if "sport80.com" in url:
        info["pattern"] = "unknown"
    return info


def extract_event_page(url: str, html: str | None = None) -> dict:
    """Full extraction pipeline: fetch → parse → classify → structure.
    
    If html is provided, skip the network fetch (for offline/mock tests).
    """
    if html is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")

    # Extract structured link sections
    sections = extract_all_links(soup)

    # Extract inline metadata
    page_text = soup.get_text("\n", strip=True)
    inline_metadata = extract_inline_metadata(page_text)

    # Extract title and overview
    overview = extract_event_title_and_overview(soup)

    # Group sections by info_type
    by_type: dict[str, list] = {}
    unclassified = []
    for s in sections:
        itype = s["info_type"]
        if itype:
            by_type.setdefault(itype, []).append(s)
            if "sport80" in s["url"]:
                s["sport80"] = classify_sport80_url(s["url"])
        else:
            unclassified.append(s)

    return {
        "source_url": url,
        "title": overview.get("title", ""),
        "dates_raw": overview.get("dates_raw", ""),
        "venue_raw": overview.get("venue_raw", ""),
        "location_raw": overview.get("location_raw", ""),
        "metadata": inline_metadata,
        "info_by_type": by_type,
        "unclassified": unclassified,
        "total_links": len(sections),
        "classified_count": sum(len(v) for v in by_type.values()),
        "unclassified_count": len(unclassified),
    }


def format_markdown(result: dict) -> str:
    """Format extraction result as readable markdown."""
    lines = []
    lines.append(f"# {result['title']}")
    lines.append(f"**Source:** {result['source_url']}")
    lines.append(f"**Dates:** {result.get('dates_raw', 'N/A')}")
    lines.append(f"**Venue:** {result.get('venue_raw', 'N/A')}")
    lines.append(f"**Location:** {result.get('location_raw', 'N/A')}")
    lines.append("")

    meta = result.get("metadata", {})
    if meta:
        lines.append("## Event Metadata")
        for k, v in meta.items():
            if isinstance(v, dict):
                lines.append(f"- **{k}:**")
                for sk, sv in v.items():
                    if isinstance(sv, dict):
                        lines.append(f"  - {sk}: {sv.get('fee', '')} closes {sv.get('closes', '')}")
                    else:
                        lines.append(f"  - {sk}: {sv}")
            else:
                lines.append(f"- **{k}:** {v}")
        lines.append("")

    lines.append("## Extracted Information")
    lines.append(f"*{result['classified_count']}/{result['total_links']} links classified*\n")

    category_order = ["registration", "reference", "schedule", "spectator", "travel", "media"]
    category_labels = {
        "registration": "Registration",
        "reference": "Reference & Policies",
        "schedule": "Schedules & Results",
        "spectator": "Spectator Info",
        "travel": "Travel & Venues",
        "media": "Media",
    }

    type_to_category = {k: v["category"] for k, v in INFO_TYPES.items()}
    type_to_desc = {k: v["description"] for k, v in INFO_TYPES.items()}

    by_type = result.get("info_by_type", {})

    for cat in category_order:
        cat_items = [(itype, items) for itype, items in by_type.items()
                     if type_to_category.get(itype) == cat]
        if not cat_items:
            continue

        lines.append(f"### {category_labels.get(cat, cat)}")
        for itype, items in sorted(cat_items):
            desc = type_to_desc.get(itype, itype)
            for item in items:
                status = item.get("status", "available")
                status_emoji = {"available": "✅", "TBA": "⏳", "missing": "❌"}.get(status, "")
                url = item.get("url", "")
                header = item.get("h3_header", item.get("link_text", ""))
                sport80_info = item.get("sport80", {})
                sport80_note = ""
                if sport80_info and "meet_id" in sport80_info:
                    sport80_note = f" (Sport80 meet_id: {sport80_info['meet_id']}, pattern: {sport80_info.get('pattern', '?')})"
                if header:
                    lines.append(f"- **{header}** {status_emoji} — {desc}{sport80_note}")
                    lines.append(f"  `{url}`")
                else:
                    lines.append(f"- {status_emoji} {desc}{sport80_note}")
                    lines.append(f"  `{url}`")
        lines.append("")

    unclassified = result.get("unclassified", [])
    if unclassified:
        lines.append(f"### ⚠️ Unclassified ({len(unclassified)} links)")
        for item in unclassified:
            header = item.get("h3_header", "")
            url = item.get("url", "")
            text = item.get("link_text", "")
            label = header or text or "(no label)"
            lines.append(f"- **{label}** → `{url}`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Extract structured info from USAW event pages")
    parser.add_argument("url", help="USAW event page URL")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--markdown", action="store_true", help="Output as markdown (default)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show unclassified links")
    args = parser.parse_args()

    result = extract_event_page(args.url)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        md = format_markdown(result)
        if not args.verbose:
            md = re.sub(r"### ⚠️ Unclassified.*?(?=\n###|\Z)", "", md, flags=re.DOTALL)
        print(md)


if __name__ == "__main__":
    main()