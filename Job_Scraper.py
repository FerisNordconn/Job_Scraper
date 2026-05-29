"""
Job Scraper Dashboard
=====================

A Flask web application that scrapes job listings from:
- Indeed Hungary
- LinkedIn
- Profession.hu

Results are stored in SQLite and displayed in a dashboard.

Requirements:
    pip install flask selenium

You also need:
    - msedgedriver.exe
    OR
    - chromedriver.exe

Run:
    python Job_Scraper.py
"""
from datetime import datetime
from urllib.parse import quote_plus

from flask import Flask, render_template_string, request, redirect, url_for

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import os
import re
import shutil
import sqlite3
import time
import json


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

DB_NAME = "jobs.db"

# Known local webdriver paths to try if PATH lookup fails
KNOWN_DRIVER_PATHS = [
    r"C:\WebDrivers\msedgedriver.exe",
    r"C:\WebDrivers\chromedriver.exe",
    r"C:\WebDrivers\geckodriver.exe",
]

app = Flask(__name__)


# -------------------------------------------------------------------
# DATABASE
# -------------------------------------------------------------------

def create_table():
    """
    Ensure the SQLite jobs table exists.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            company TEXT,
            location TEXT,
            link TEXT,
            search_term TEXT,
            timestamp TEXT,
            hot_flag INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def save_job(title, company, location, link, search_term):
    """
    Insert a new job row into the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO jobs
        (title, company, location, link, search_term, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, company, location, link, search_term, timestamp))
    conn.commit()
    conn.close()


def get_all_jobs():
    """
    Retrieve all saved jobs sorted by newest first.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, company, location,
               link, search_term, timestamp, hot_flag
        FROM jobs
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def update_hot_flag(job_id, hot_flag):
    """
    Toggle the HOT flag on a job row.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE jobs
        SET hot_flag = ?
        WHERE id = ?
    """, (hot_flag, job_id))
    conn.commit()
    conn.close()


def delete_job(job_id):
    """
    Delete a job row by ID.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM jobs
        WHERE id = ?
    """, (job_id,))
    conn.commit()
    conn.close()


def clear_all_jobs():
    """
    Delete all rows from the jobs table.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs")
    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# DRIVER
# -------------------------------------------------------------------

def local_driver_path(names):
    """
    Find a webdriver executable in PATH or in known local locations.
    """
    for name in names:
        path = shutil.which(name)
        if path:
            return path

    for known_path in KNOWN_DRIVER_PATHS:
        for name in names:
            if os.path.basename(known_path).lower() == name.lower() and os.path.isfile(known_path):
                return known_path

    return None


def get_driver():
    """
    Start a Selenium webdriver using Edge, Chrome, or Firefox.
    Applies stealth settings to reduce bot-detection fingerprinting.
    """
    drivers = [
        ("Edge",    EdgeService,    webdriver.Edge,    ["msedgedriver.exe", "msedgedriver"],  webdriver.EdgeOptions),
        ("Chrome",  ChromeService,  webdriver.Chrome,  ["chromedriver.exe", "chromedriver"],   webdriver.ChromeOptions),
        ("Firefox", FirefoxService, webdriver.Firefox, ["geckodriver.exe",  "geckodriver"],    webdriver.FirefoxOptions),
    ]

    for name, service_cls, driver_cls, executable_names, options_cls in drivers:
        driver_path = local_driver_path(executable_names)
        if not driver_path:
            continue

        try:
            options = options_cls()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--window-size=1920,1080")

            # Realistic user-agent — critical for Indeed bot detection
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )

            if name in ["Edge", "Chrome"]:
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option("useAutomationExtension", False)

            service = service_cls(driver_path) if name != "Firefox" else service_cls(executable_path=driver_path)
            driver = driver_cls(service=service, options=options)

            # Mask the `navigator.webdriver` JS property
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            return driver

        except Exception:
            continue

    return "No compatible webdriver found."


# -------------------------------------------------------------------
# SCRAPING
# -------------------------------------------------------------------

def clean_text(text):
    """
    Normalize whitespace in scraped text.
    """
    return re.sub(r"\s+", " ", (text or "")).strip()


def dismiss_indeed_overlays(driver, debug_log):
    """
    Attempt to dismiss cookie banners, consent popups and CAPTCHA walls
    that Indeed shows before actual results.
    """
    # Cookie / consent button patterns Indeed uses
    consent_selectors = [
        "button[id*='onetrust-accept']",
        "button[id*='accept']",
        "#onetrust-accept-btn-handler",
        "button.icl-Button--primary",
        "[data-testid='cookie-consent-accept']",
    ]
    for sel in consent_selectors:
        try:
            btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            btn.click()
            debug_log.append(f"[Indeed] dismissed overlay via {sel!r}")
            time.sleep(1)
            break
        except Exception:
            pass

    # If we landed on the "before you continue" / "Are you human?" page,
    # log it so the caller knows scraping may yield zero results.
    if "before you continue" in driver.title.lower() or "are you a robot" in driver.page_source.lower():
        debug_log.append("[Indeed] Anti-bot wall detected — results may be empty")


def _extract_json_object(text, start_marker):
    """
    Extract a JS object literal from page source starting at start_marker.
    """
    match = re.search(re.escape(start_marker), text)
    if not match:
        return None

    start = text.find("{", match.end())
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _decode_indeed_value(value):
    """
    Normalize a value that may be a string or a JSON object with a 'text' field.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value:
            return value["text"]
        if "label" in value:
            return value["label"]
    return ""


def _search_for_indeed_job_list(data):
    """
    Recursively search a parsed JSON object for a list of Indeed job records.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict) and any(
                    field in first
                    for field in (
                        "jobTitle",
                        "companyName",
                        "formattedLocation",
                        "jobkey",
                        "jobUrl",
                        "title",
                    )
                ):
                    return value
            result = _search_for_indeed_job_list(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _search_for_indeed_job_list(item)
            if result:
                return result
    return None


def _parse_indeed_json(page_source, default_location, debug_log):
    """
    Parse embedded Indeed JSON from window.mosaic.providerData.
    """
    json_text = _extract_json_object(page_source, "window.mosaic.providerData")
    if not json_text:
        json_text = _extract_json_object(page_source, "mosaic.providerData")
    if not json_text:
        debug_log.append("[Indeed JSON] providerData not found")
        return []

    try:
        provider_data = json.loads(json_text)
    except Exception as exc:
        debug_log.append(f"[Indeed JSON] parse failed: {exc}")
        return []

    job_list = _search_for_indeed_job_list(provider_data)
    if not job_list:
        debug_log.append("[Indeed JSON] no job list found")
        return []

    jobs = []
    for item in job_list[:8]:
        if not isinstance(item, dict):
            continue

        title = _decode_indeed_value(item.get("jobTitle") or item.get("title") or item.get("position"))
        company = _decode_indeed_value(
            item.get("companyName")
            or item.get("company")
            or item.get("formattedCompanyName")
            or item.get("formattedCompany")
        )
        loc = _decode_indeed_value(
            item.get("formattedLocation")
            or item.get("jobLocation")
            or item.get("location")
            or default_location
        )
        link = item.get("jobUrl") or item.get("detailUrl") or item.get("url") or ""
        if not link:
            jk = item.get("jobKey") or item.get("jobkey") or item.get("jk") or item.get("jobId")
            if jk:
                link = f"https://hu.indeed.com/viewjob?jk={jk}"
        if link.startswith("/"):
            link = "https://hu.indeed.com" + link

        title = clean_text(title)
        company = clean_text(company) or "(no company)"
        loc = clean_text(loc) or default_location

        if title:
            jobs.append((title, company, loc, link, f"{search_term} in {default_location}"))
    debug_log.append(f"[Indeed JSON] extracted {len(jobs)} jobs")
    return jobs


def scrape_indeed(driver, search_term, location, debug_log):
    """
    Scrape jobs from Indeed Hungary.
    First attempt embedded JSON extraction, then fall back to DOM parsing.
    """
    jobs = []
    q = quote_plus(search_term)
    loc_q = quote_plus(location)
    indeed_url = f"https://hu.indeed.com/jobs?q={q}&l={loc_q}&lang=en"

    driver.get(indeed_url)
    time.sleep(3)
    dismiss_indeed_overlays(driver, debug_log)

    page_source = driver.page_source
    jobs = _parse_indeed_json(page_source, location, debug_log)
    if jobs:
        return jobs

    debug_log.append("[Indeed] JSON fallback did not return results; using DOM fallback")

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#mosaic-provider-jobcards [data-testid='slider_item'], [data-testid='slider_item']")
            )
        )
    except Exception as e:
        debug_log.append(f"[Indeed DOM wait] {e}")

    time.sleep(2)
    cards = driver.find_elements(
        By.CSS_SELECTOR,
        "#mosaic-provider-jobcards [data-testid='slider_item'], [data-testid='slider_item'], a.tapItem, div.job_seen_beacon"
    )
    debug_log.append(f"[Indeed DOM] found {len(cards)} cards")

    for idx, card in enumerate(cards[:8], start=1):
        try:
            card_text = clean_text(card.get_attribute("innerText") or "")
            debug_log.append(f"[Indeed Card {idx}] text={card_text[:120]!r}")

            title = _extract_indeed_title(card, card_text, debug_log, idx)
            company = _extract_indeed_company(card, card_text)
            loc = _extract_indeed_location(card, location)
            link = _extract_indeed_link(card)

            if title:
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            else:
                debug_log.append(f"[Indeed Card {idx}] skipped — no title extracted")

        except Exception as exc:
            debug_log.append(f"[Indeed Card {idx}] exception: {exc}")

    return jobs


def _extract_indeed_title(card, card_text, debug_log, idx):
    """Return the job title from an Indeed card element."""
    # 1. data-testid (most reliable, survives CSS class churn)
    for sel in [
        "[data-testid='jobTitle'] span",
        "[data-testid='jobTitle']",
        "h2[data-testid='jobTitle'] span",
        "h2[data-testid='jobTitle']",
    ]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            text = clean_text(el.text)
            if text and text.lower() not in ("új", "new", "easy apply", "uj"):
                return text
        except Exception:
            pass

    # 2. Generic h2 span (works for older page variants)
    try:
        spans = card.find_elements(By.CSS_SELECTOR, "h2 span")
        for span in reversed(spans):
            text = clean_text(span.text)
            if text and text.lower() not in ("új", "new", "easy apply", "uj"):
                return text
    except Exception:
        pass

    # 3. Any anchor whose href points to /rc/clk or /pagead — those are job links
    try:
        for a in card.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href") or ""
            if "/rc/clk" in href or "/pagead" in href or "/jobs/view" in href:
                text = clean_text(a.text)
                if text:
                    return text
    except Exception:
        pass

    # 4. Plain text first line
    if card_text:
        lines = [ln.strip() for ln in card_text.splitlines() if ln.strip()]
        if lines:
            return lines[0]

    return ""


def _extract_indeed_company(card, card_text):
    """Return the company name from an Indeed card element."""
    selectors = [
        "[data-testid='company-name']",
        "span[data-testid='company-name']",
        ".companyName",
        ".companyName a",
        "[class*='companyName']",
        "span[class*='company']",
    ]
    for sel in selectors:
        try:
            text = clean_text(card.find_element(By.CSS_SELECTOR, sel).text)
            if text:
                return text
        except Exception:
            pass

    # Fallback: second non-empty line of card text
    if card_text:
        lines = [ln.strip() for ln in card_text.splitlines() if ln.strip()]
        if len(lines) > 1:
            return lines[1]

    return "(no company)"


def _extract_indeed_location(card, default_location):
    """Return the location string from an Indeed card element."""
    selectors = [
        "[data-testid='text-location']",
        ".companyLocation",
        "[class*='location']",
        "div[class*='location']",
        "span[class*='location']",
    ]
    for sel in selectors:
        try:
            text = clean_text(card.find_element(By.CSS_SELECTOR, sel).text)
            if text:
                return text
        except Exception:
            pass
    return default_location


def _extract_indeed_link(card):
    """Return the job detail URL from an Indeed card element."""
    # Prefer the direct job link anchor
    for sel in [
        "a[data-jk]",          # data-jk is Indeed's job key attribute
        "h2 a",
        "a[href*='/rc/clk']",
        "a[href*='/pagead']",
        "a[href*='/jobs/view']",
    ]:
        try:
            href = card.find_element(By.CSS_SELECTOR, sel).get_attribute("href") or ""
            if href:
                if href.startswith("/"):
                    href = "https://hu.indeed.com" + href
                return href
        except Exception:
            pass

    # Last resort: first anchor in the card
    try:
        href = card.find_element(By.TAG_NAME, "a").get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://hu.indeed.com" + href
        return href
    except Exception:
        return ""


# ------------------------------------------------------------------
# LinkedIn helpers (unchanged from original, kept here for completeness)
# ------------------------------------------------------------------

def scrape_linkedin_card(card, search_term, location, debug_log):
    """
    Extract title, company, location and link from a LinkedIn job card element.
    """
    title = company = loc = link = ""
    card_text = clean_text(card.get_attribute("innerText") or "")

    info = card
    try:
        info = card.find_element(By.CSS_SELECTOR, ".base-search-card__info, .job-card-container__link, .base-card__info")
    except Exception:
        info = card

    for sel in [".base-search-card__title", ".job-search-card__title", ".job-card-list__title", "h3"]:
        try:
            el = info.find_element(By.CSS_SELECTOR, sel)
            title = clean_text(el.text)
            if title:
                break
        except Exception:
            continue

    for sel in [".base-search-card__subtitle", ".job-search-card__subtitle", ".job-card-container__company-name", ".job-card-list__company-name", "h4"]:
        try:
            el = info.find_element(By.CSS_SELECTOR, sel)
            company = clean_text(el.text)
            if company:
                break
        except Exception:
            company = ""

    if not company and card_text:
        lines = [ln.strip() for ln in re.split(r"\r?\n", card_text) if ln.strip()]
        if title and lines:
            if lines[0] == title and len(lines) > 1:
                company = lines[1]
            elif len(lines) > 1:
                company = lines[1]
        elif len(lines) > 1:
            company = lines[1]

    for sel in [".job-search-card__location", ".base-search-card__metadata span", ".job-card-container__metadata-item", ".job-card__location", ".location"]:
        try:
            el = info.find_element(By.CSS_SELECTOR, sel)
            loc = clean_text(el.text)
            if loc:
                break
        except Exception:
            continue

    if not loc:
        loc = location

    try:
        a = card.find_element(By.CSS_SELECTOR, "a.base-card__full-link, a.job-card-list__title-link, a.job-card-list__title")
        link = a.get_attribute("href") or ""
    except Exception:
        try:
            a = card.find_element(By.TAG_NAME, "a")
            link = a.get_attribute("href") or ""
        except Exception:
            pass

    if title and company and title.lower() == company.lower():
        lines = [ln.strip() for ln in re.split(r"\r?\n", card_text) if ln.strip()]
        if len(lines) >= 2 and lines[0] == title:
            company = lines[1] if lines[1].lower() != title.lower() else ""

    if not title and card_text:
        lines = [ln.strip() for ln in re.split(r"\r?\n", card_text) if ln.strip()]
        if lines:
            title = lines[0]

    debug_log.append(f"[LinkedIn card] title={title!r}, company={company!r}, location={loc!r}")
    return title, company, loc, link


def scrape_jobs(search_term, location):
    """
    Main scraper function.
    Scrapes up to 8 jobs from Indeed and 5 each from LinkedIn and Profession.hu.
    """
    driver = get_driver()
    if isinstance(driver, str):
        return driver, []

    jobs = []
    debug_log = []

    q = quote_plus(search_term)
    loc_q = quote_plus(location)

    try:
        # ------------------------------------------------------------------
        # INDEED HUNGARY
        # ------------------------------------------------------------------
        indeed_jobs = scrape_indeed(driver, search_term, location, debug_log)
        jobs.extend(indeed_jobs)
        debug_log.append(f"[Indeed] collected {len(indeed_jobs)} jobs")

        # ------------------------------------------------------------------
        # LINKEDIN
        # ------------------------------------------------------------------
        linkedin_url = (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={search_term}&location={location}"
        )
        driver.get(linkedin_url)

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "ul.jobs-search__results-list li, .jobs-search-results__list li")
                )
            )
        except Exception:
            pass

        time.sleep(2)

        linkedin_cards = driver.find_elements(
            By.CSS_SELECTOR,
            "ul.jobs-search__results-list li, .jobs-search-results__list li, .job-card-container, .base-card"
        )

        for card in linkedin_cards[:5]:
            try:
                title = company = loc = link = ""

                for sel in [
                    ".base-search-card__title",
                    ".job-search-card__title",
                    ".job-card-list__title",
                    ".result-card__title",
                    "h3",
                    "a"
                ]:
                    try:
                        el = card.find_element(By.CSS_SELECTOR, sel)
                        title = el.text.strip()
                        if title:
                            break
                    except Exception:
                        continue

                for sel in [
                    ".base-search-card__subtitle",
                    ".job-search-card__subtitle",
                    ".result-card__subtitle",
                    ".job-card-container__company-name",
                    "h4"
                ]:
                    try:
                        el = card.find_element(By.CSS_SELECTOR, sel)
                        company = el.text.strip()
                        break
                    except Exception:
                        company = ""

                for sel in [
                    ".job-search-card__location",
                    ".base-search-card__metadata > span",
                    ".job-card-container__metadata-item",
                    ".job-card__location",
                    ".job-search-card__location"
                ]:
                    try:
                        el = card.find_element(By.CSS_SELECTOR, sel)
                        loc = el.text.strip()
                        break
                    except Exception:
                        loc = location

                try:
                    a = card.find_element(By.CSS_SELECTOR, "a.base-card__full-link, a.job-card-list__title-link, a.job-card-list__title")
                    link = a.get_attribute("href") or ""
                except Exception:
                    try:
                        link = card.get_attribute("href") or ""
                    except Exception:
                        link = ""

                if not title:
                    text = card.get_attribute("innerText") or ""
                    title = text.split("\n")[0].strip()

                jobs.append((
                    title or "(no title)",
                    company or "(no company)",
                    loc or location,
                    link or "",
                    f"{search_term} in {location}"
                ))

            except Exception as e:
                debug_log.append(f"[LinkedIn Card] {str(e)}")
                continue

        # ------------------------------------------------------------------
        # PROFESSION.HU
        # ------------------------------------------------------------------
        profession_url = (
            "https://www.profession.hu/allasok?"
            f"keyword={quote_plus(search_term)}&location={quote_plus(location)}"
        )

        driver.get(profession_url)

        # Wait until cards appear
        try:
            WebDriverWait(driver, 15).until(
                lambda d: len(
                    d.find_elements(
                        By.CSS_SELECTOR,
                        "article, .job-card, .job-item, .search-result, "
                        ".search-result-item, a[href*='/allas/']"
                    )
                ) > 3
            )
        except Exception as e:
            debug_log.append(f"[Profession Wait] {str(e)}")

        # Profession.hu lazy-loads content
        try:
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight/2);"
            )
            time.sleep(2)

            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(2)
        except Exception:
            pass

        prof_cards = driver.find_elements(
            By.CSS_SELECTOR,
            (
                "article.job-card, "
                "article.job-item, "
                "div.job-card, "
                "div.job-item, "
                "li.job-item, "
                ".search-result, "
                ".search-result-item, "
                "a[href*='/allas/']"
            )
        )

        debug_log.append(f"[Profession] Found {len(prof_cards)} cards")

        seen_links = set()

        for card in prof_cards:
            try:
                href = ""
                card_text = clean_text(
                    card.get_attribute("innerText") or ""
                )

                # ----------------------------------------------------------
                # LINK
                # ----------------------------------------------------------
                if card.tag_name.lower() == "a":
                    href = card.get_attribute("href") or ""
                else:
                    try:
                        a = card.find_element(
                            By.CSS_SELECTOR,
                            "a[href*='/allas/']"
                        )
                        href = a.get_attribute("href") or ""
                    except Exception:
                        pass

                if not href or "/allas" not in href:
                    continue

                if href in seen_links:
                    continue

                # ----------------------------------------------------------
                # TITLE
                # ----------------------------------------------------------
                title = "(no title)"

                title_selectors = [
                    "h1",
                    "h2",
                    "h3",
                    ".job-card__title",
                    ".job-card-title",
                    ".job-title",
                    ".position",
                    ".title",
                    "a[href*='/allas/']"
                ]

                for sel in title_selectors:
                    try:
                        elements = card.find_elements(
                            By.CSS_SELECTOR,
                            sel
                        )

                        for el in elements:
                            txt = clean_text(el.text)

                            if (
                                txt
                                and len(txt) > 2
                                and "jelentkez" not in txt.lower()
                            ):
                                title = txt
                                break

                        if title != "(no title)":
                            break

                    except Exception:
                        continue

                # fallback
                if title == "(no title)" and card_text:
                    lines = [
                        ln.strip()
                        for ln in card_text.splitlines()
                        if ln.strip()
                    ]

                    if lines:
                        title = lines[0]

                # ----------------------------------------------------------
                # COMPANY
                # ----------------------------------------------------------
                company = "(no company)"

                company_selectors = [
                    ".company-name",
                    ".company",
                    ".employer",
                    ".job-card__company-name",
                    ".job-card__company",
                    ".job-card-company",
                    ".company-link",
                    ".job-ad-company",
                    ".company-title",
                    ".job-company",
                    "a[href*='/ceg/']",
                    "a[href*='/munkaado/']",
                    "div[class*='company']",
                    "span[class*='company']",
                    "h3",
                ]

                for sel in company_selectors:
                    try:
                        elements = card.find_elements(
                            By.CSS_SELECTOR,
                            sel
                        )

                        for el in elements:
                            txt = clean_text(el.text)

                            if (
                                txt
                                and len(txt) > 1
                                and txt.lower() != title.lower()
                                and location.lower() not in txt.lower()
                                and not re.search(
                                    r"\d+\s*(ft|huf|eur|€)",
                                    txt,
                                    re.I
                                )
                            ):
                                company = txt
                                break

                        if company != "(no company)":
                            break

                    except Exception:
                        continue

                # smart fallback
                if company == "(no company)" and card_text:
                    lines = [
                        ln.strip()
                        for ln in card_text.splitlines()
                        if ln.strip()
                    ]

                    filtered = []

                    for ln in lines:
                        lower = ln.lower()

                        if (
                            lower == title.lower()
                            or location.lower() in lower
                            or re.search(r"\d+\s*(ft|huf|eur|€)", lower, re.I)
                            or "jelentkez" in lower
                            or "állás" in lower
                            or "munka" in lower
                        ):
                            continue

                        filtered.append(ln)

                    if filtered:
                        company = filtered[0]

                # ----------------------------------------------------------
                # LOCATION
                # ----------------------------------------------------------
                loc = location

                location_selectors = [
                    ".job-card__location",
                    ".location",
                    ".job-location",
                    ".job-card__info-item--location",
                    "span[class*='location']",
                    "div[class*='location']",
                ]

                for sel in location_selectors:
                    try:
                        elements = card.find_elements(
                            By.CSS_SELECTOR,
                            sel
                        )

                        for el in elements:
                            txt = clean_text(el.text)

                            if txt:
                                loc = txt
                                break

                        if loc != location:
                            break

                    except Exception:
                        continue

                jobs.append((
                    title,
                    company,
                    loc,
                    href,
                    f"{search_term} in {location}"
                ))

                seen_links.add(href)

                debug_log.append(
                    f"[Profession OK] {title} | {company} | {href}"
                )

                if len(seen_links) >= 5:
                    break

            except Exception as e:
                debug_log.append(f"[Profession Card] {str(e)}")


# -------------------------------------------------------------------
# ROUTES
# -------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def dashboard():
    """
    Main web dashboard route.
    """
    error = None
    if request.method == "POST":
        if "scrape" in request.form:
            search_term = request.form.get("search_term", "SAP SuccessFactor")
            location = request.form.get("location", "Budapest")
            result, debug_log = scrape_jobs(search_term, location)
            if isinstance(result, str):
                error = result
            else:
                for job in result:
                    save_job(*job)
                if not result:
                    error = "No jobs found.<br><br>" + "<br>".join(debug_log)
                else:
                    return redirect(url_for("dashboard"))
        elif "clear" in request.form:
            clear_all_jobs()
            return redirect(url_for("dashboard"))

    jobs = get_all_jobs()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Job Dashboard</title>
        <style>
            body { font-family: Arial; margin: 20px; background: #f5f5f5; }
            .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
            th { background: #4CAF50; color: white; }
            tr:hover { background: #f9f9f9; }
            .button { padding: 8px 12px; border: none; color: white; cursor: pointer; background: #4CAF50; border-radius: 4px; margin: 2px; }
            .delete { background: #f44336; }
            .hot { color: red; font-weight: bold; }
            .error { color: red; background: #ffe5e5; padding: 10px; border-radius: 4px; }
            input[type="text"] { padding: 10px; margin: 5px; border: 1px solid #ddd; border-radius: 4px; }
            form { margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Job Scraper Dashboard</h1>
    """
    if error:
        html += f'<p class="error">{error}</p>'
    html += """
        <form method="post">
            <input type="text" name="search_term" placeholder="Search term" value="SAP SuccessFactor">
            <input type="text" name="location" placeholder="Location" value="Budapest">
            <button type="submit" name="scrape" class="button">Scrape Jobs</button>
            <button type="submit" name="clear" class="button delete">Clear All</button>
        </form>
        <p>Total jobs: <strong>""" + str(len(jobs)) + """</strong></p>
        <table>
            <tr>
                <th>ID</th><th>Title</th><th>Company</th><th>Location</th><th>Link</th><th>Search</th><th>Timestamp</th><th>HOT</th><th>Actions</th>
            </tr>
    """
    for row in jobs:
        hot_class = "hot" if row[7] else ""
        html += f"""
            <tr>
                <td>{row[0]}</td>
                <td>{row[1]}</td>
                <td>{row[2]}</td>
                <td>{row[3]}</td>
                <td><a href="{row[4]}" target="_blank">Open</a></td>
                <td>{row[5]}</td>
                <td>{row[6]}</td>
                <td class="{hot_class}">{'Yes' if row[7] else 'No'}</td>
                <td>
                    <form action="/toggle_hot" method="post" style="display:inline;">
                        <input type="hidden" name="job_id" value="{row[0]}">
                        <button type="submit" class="button">Toggle HOT</button>
                    </form>
                    <form action="/delete" method="post" style="display:inline;">
                        <input type="hidden" name="job_id" value="{row[0]}">
                        <button type="submit" class="button delete">Delete</button>
                    </form>
                </td>
            </tr>
        """
    html += """
        </table>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/toggle_hot", methods=["POST"])
def toggle_hot():
    """
    Toggle the hot flag for a job.
    """
    job_id = int(request.form["job_id"])
    current_jobs = get_all_jobs()
    hot_flag = 1 if not any(r[0] == job_id and r[7] for r in current_jobs) else 0
    update_hot_flag(job_id, hot_flag)
    return redirect(url_for("dashboard"))


@app.route("/delete", methods=["POST"])
def delete():
    """
    Remove a job from the database.
    """
    job_id = request.form["job_id"]
    delete_job(job_id)
    return redirect(url_for("dashboard"))


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

if __name__ == "__main__":
    create_table()
    print("\n" + "=" * 50)
    print("Job Scraper Dashboard")
    print("=" * 50)
    print("Open: http://127.0.0.1:5000")
    print("=" * 50 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=True)