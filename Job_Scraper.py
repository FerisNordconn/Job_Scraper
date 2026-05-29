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

import os
import shutil
import sqlite3
import time
from datetime import datetime

from flask import Flask, render_template_string, request, redirect, url_for

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

DB_NAME = "jobs.db"

KNOWN_DRIVER_PATHS = [
    r"C:\WebDrivers\msedgedriver.exe",
]

app = Flask(__name__)


# -------------------------------------------------------------------
# DATABASE
# -------------------------------------------------------------------

def create_table():
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM jobs
        WHERE id = ?
    """, (job_id,))

    conn.commit()
    conn.close()


def clear_all_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM jobs")

    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# DRIVER
# -------------------------------------------------------------------

def local_driver_path(names):

    for name in names:
        path = shutil.which(name)

        if path:
            return path

    for known_path in KNOWN_DRIVER_PATHS:

        for name in names:

            if (
                os.path.basename(known_path).lower() == name.lower()
                and os.path.isfile(known_path)
            ):
                return known_path

    return None


def get_driver():

    drivers = [
        (
            "Edge",
            EdgeService,
            webdriver.Edge,
            ["msedgedriver.exe", "msedgedriver"],
            webdriver.EdgeOptions,
        ),
        (
            "Chrome",
            ChromeService,
            webdriver.Chrome,
            ["chromedriver.exe", "chromedriver"],
            webdriver.ChromeOptions,
        ),
        (
            "Firefox",
            FirefoxService,
            webdriver.Firefox,
            ["geckodriver.exe", "geckodriver"],
            webdriver.FirefoxOptions,
        ),
    ]

    for (
        name,
        service_cls,
        driver_cls,
        executable_names,
        options_cls,
    ) in drivers:

        driver_path = local_driver_path(executable_names)

        if not driver_path:
            continue

        try:
            options = options_cls()

            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")

            # Anti-bot options
            options.add_argument(
                "--disable-blink-features=AutomationControlled"
            )

            if name in ["Edge", "Chrome"]:
                options.add_experimental_option(
                    "excludeSwitches",
                    ["enable-automation"]
                )

                options.add_experimental_option(
                    "useAutomationExtension",
                    False
                )

            service = (
                service_cls(driver_path)
                if name != "Firefox"
                else service_cls(executable_path=driver_path)
            )

            driver = driver_cls(
                service=service,
                options=options
            )

            return driver

        except Exception:
            continue

    return "No compatible webdriver found."


# -------------------------------------------------------------------
# SCRAPING
# -------------------------------------------------------------------

def scrape_jobs(search_term, location):

    driver = get_driver()

    if isinstance(driver, str):
        return driver, []

    jobs = []
    debug_log = []

    try:

        # -----------------------------------------------------------
        # INDEED
        # -----------------------------------------------------------

        indeed_url = (
            f"https://hu.indeed.com/jobs"
            f"?q={search_term}&l={location}"
        )

        driver.get(indeed_url)

        time.sleep(5)

        indeed_cards = driver.find_elements(
            By.CLASS_NAME,
            "job_seen_beacon"
        )

        for card in indeed_cards[:5]:

            try:
                title = card.find_element(
                    By.CLASS_NAME,
                    "jobTitle"
                ).text

                company = card.find_element(
                    By.CLASS_NAME,
                    "companyName"
                ).text

                loc = card.find_element(
                    By.CLASS_NAME,
                    "companyLocation"
                ).text

                link = card.find_element(
                    By.TAG_NAME,
                    "a"
                ).get_attribute("href")

                jobs.append((
                    title,
                    company,
                    loc,
                    link,
                    f"{search_term} in {location}"
                ))

            except Exception as e:
                debug_log.append(f"[Indeed] {str(e)}")

        # -----------------------------------------------------------
        # LINKEDIN (robust selectors + fallbacks to ensure title/company/location)
        # -----------------------------------------------------------

        linkedin_url = (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={search_term}&location={location}"
        )

        driver.get(linkedin_url)

        # wait for results list if present
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

                # Title - try multiple selectors then fallback to innerText
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

                # Location - try first so we can exclude it from heuristics later
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

                # Company - try targeted selectors first
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
                        if company:
                            break
                    except Exception:
                        company = ""

                # If still empty, try anchor that likely points to company page
                if not company:
                    try:
                        a_company = card.find_element(By.CSS_SELECTOR, "a[href*='/company/'], a[href*='company-']")
                        company = a_company.text.strip() or a_company.get_attribute("aria-label") or ""
                    except Exception:
                        company = ""

                # Final heuristic: parse innerText and pick a sensible line
                if not company:
                    text = (card.get_attribute("innerText") or "").strip()
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    # remove title and location lines
                    candidates = [ln for ln in lines if ln != title and ln != loc]
                    for ln in candidates:
                        low = ln.lower()
                        if low in ("save", "easy apply", "apply on company site", "new"):
                            continue
                        company = ln
                        break

                # Link - prefer anchor href
                try:
                    a = card.find_element(By.CSS_SELECTOR, "a")
                    link = a.get_attribute("href") or ""
                except Exception:
                    try:
                        link = card.get_attribute("href") or ""
                    except Exception:
                        link = ""

                # final text fallback if title still empty
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
                try:
                    debug_log.append(f"[LinkedIn Card] {str(e)}")
                except Exception:
                    pass
                continue

        # ----------------------------------------------------------------------------------------------------------
        # PROFESSION.HU
        # ----------------------------------------------------------------------------------------------------------

        profession_url = (
            f"https://www.profession.hu/allasok/"
            f"{search_term.replace(' ', '-')}/"
            f"{location.lower()}"
        )

        driver.get(profession_url)

        time.sleep(5)

        prof_cards = driver.find_elements(
            By.CLASS_NAME,
            "job-card"
        )

        for card in prof_cards[:5]:

            try:

                title = card.find_element(
                    By.TAG_NAME,
                    "h2"
                ).text

                company = card.find_element(
                    By.CLASS_NAME,
                    "company-name"
                ).text

                link = card.find_element(
                    By.TAG_NAME,
                    "a"
                ).get_attribute("href")

                jobs.append((
                    title,
                    company,
                    location,
                    link,
                    f"{search_term} in {location}"
                ))

            except Exception as e:
                debug_log.append(
                    f"[Profession] {str(e)}"
                )

    finally:
        driver.quit()

    return jobs, debug_log


# ---------------------------------------------------------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def dashboard():

    error = None

    if request.method == "POST":

        if "scrape" in request.form:

            search_term = request.form.get(
                "search_term",
                "SAP SuccessFactor"
            )

            location = request.form.get(
                "location",
                "Budapest"
            )

            result, debug_log = scrape_jobs(
                search_term,
                location
            )

            if isinstance(result, str):
                error = result

            else:

                for job in result:
                    save_job(*job)

                if not result:

                    error = (
                        "No jobs found.<br><br>"
                        + "<br>".join(debug_log)
                    )

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

            body {
                font-family: Arial;
                margin: 20px;
                background: #f5f5f5;
            }

            .container {
                background: white;
                padding: 20px;
                border-radius: 8px;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }

            th, td {
                border: 1px solid #ddd;
                padding: 10px;
            }

            th {
                background: #4CAF50;
                color: white;
            }

            .button {
                padding: 8px 12px;
                border: none;
                color: white;
                cursor: pointer;
                background: #4CAF50;
            }

            .delete {
                background: red;
            }

            .hot {
                color: red;
                font-weight: bold;
            }

            .error {
                color: red;
            }

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

            <input
                type="text"
                name="search_term"
                value="SAP SuccessFactor"
            >

            <input
                type="text"
                name="location"
                value="Budapest"
            >

            <button
                type="submit"
                name="scrape"
                class="button"
            >
                Scrape Jobs
            </button>

            <button
                type="submit"
                name="clear"
                class="button delete"
            >
                Clear All
            </button>

        </form>

        <p>Total jobs: <strong>
    """

    html += str(len(jobs)) + "</strong></p>"

    html += """
        <table>

            <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Company</th>
                <th>Location</th>
                <th>Link</th>
                <th>Search</th>
                <th>Timestamp</th>
                <th>HOT</th>
                <th>Actions</th>
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

            <td>
                <a href="{row[4]}" target="_blank">
                    Open
                </a>
            </td>

            <td>{row[5]}</td>
            <td>{row[6]}</td>

            <td class="{hot_class}">
                {'Yes' if row[7] else 'No'}
            </td>

            <td>

                <form
                    action="/toggle_hot"
                    method="post"
                    style="display:inline;"
                >

                    <input
                        type="hidden"
                        name="job_id"
                        value="{row[0]}"
                    >

                    <button
                        type="submit"
                        class="button"
                    >
                        Toggle HOT
                    </button>

                </form>

                <form
                    action="/delete"
                    method="post"
                    style="display:inline;"
                >

                    <input
                        type="hidden"
                        name="job_id"
                        value="{row[0]}"
                    >

                    <button
                        type="submit"
                        class="button delete"
                    >
                        Delete
                    </button>

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

    job_id = int(request.form["job_id"])

    current_jobs = get_all_jobs()

    hot_flag = (
        1
        if not any(
            r[0] == job_id and r[7]
            for r in current_jobs
        )
        else 0
    )

    update_hot_flag(job_id, hot_flag)

    return redirect(url_for("dashboard"))


@app.route("/delete", methods=["POST"])
def delete():

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

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
