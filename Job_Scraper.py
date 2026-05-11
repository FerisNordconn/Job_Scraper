"""
Job Scraper Dashboard
=====================
A Flask web application that scrapes job listings from Indeed (Hungarian),
LinkedIn, and prof.hu using Selenium. Results are stored in a local SQLite
database and displayed in a browser-based dashboard with hot-flagging and
deletion features.

Dependencies:
    - Flask         (web server & templating)
    - Selenium      (browser automation for scraping)
    - sqlite3       (built-in; local job storage)
    - shutil        (built-in; locating webdriver binaries on PATH)
    - os            (built-in; checking hardcoded driver paths on disk)

Usage:
    python Job_Scraper.py
    Then open http://127.0.0.1:5000 in your browser.
"""

import os
import shutil
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Name of the SQLite database file stored in the same directory as this script
DB_NAME = 'jobs.db'

# Hardcoded fallback paths for webdriver binaries that are NOT on the system PATH.
# Useful when you don't have admin rights to add a directory to PATH.
# Add or remove entries here as needed; all entries are checked in order.
KNOWN_DRIVER_PATHS = [
    r"C:\WebDrivers\msedgedriver.exe",
]

# Initialize the Flask web application
app = Flask(__name__)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def create_table():
    """
    Create the `jobs` table in the SQLite database if it doesn't already exist.

    Schema:
        id          - Auto-incrementing primary key
        title       - Job title text
        company     - Company name
        location    - Job location
        link        - URL to the job posting
        search_term - The query string used when the job was scraped
        timestamp   - ISO-8601 datetime when the record was inserted
        hot_flag    - 1 if the user marked the job as HOT, 0 otherwise
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
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
    ''')
    conn.commit()
    conn.close()


def save_job(title, company, location, link, search_term):
    """
    Insert a single job record into the database with the current timestamp.

    Args:
        title       (str): Job title.
        company     (str): Hiring company name.
        location    (str): Job location string.
        link        (str): Direct URL to the job posting.
        search_term (str): Combined search label (e.g. "Python in Budapest").
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()  # e.g. "2024-05-11T14:30:00.123456"
    cursor.execute(
        'INSERT INTO jobs (title, company, location, link, search_term, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (title, company, location, link, search_term, timestamp)
    )
    conn.commit()
    conn.close()


def get_all_jobs():
    """
    Retrieve all job records from the database, newest first.

    Returns:
        list[tuple]: Each tuple contains:
            (id, title, company, location, link, search_term, timestamp, hot_flag)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, company, location, link, search_term, timestamp, hot_flag FROM jobs ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows


def update_hot_flag(job_id, hot_flag):
    """
    Set the hot_flag value for a specific job.

    Args:
        job_id   (int): Primary key of the job to update.
        hot_flag (int): 1 to mark as HOT, 0 to unmark.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE jobs SET hot_flag = ? WHERE id = ?', (hot_flag, job_id))
    conn.commit()
    conn.close()


def delete_job(job_id):
    """
    Permanently remove a single job record from the database.

    Args:
        job_id (int): Primary key of the job to delete.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()


def clear_all_jobs():
    """Delete every record from the jobs table (non-reversible)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM jobs')
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# WebDriver helpers
# ---------------------------------------------------------------------------

def local_driver_path(names):
    """
    Locate a webdriver binary by searching in two places, in order:

    1. The system PATH (via shutil.which) — works when the driver directory
       has been added to PATH by an administrator.
    2. The KNOWN_DRIVER_PATHS list — a hardcoded fallback for situations
       where PATH cannot be modified (e.g. no admin rights). Each entry is
       matched by filename against the requested binary names.

    Args:
        names (list[str]): Ordered list of binary filenames to look for
                           (e.g. ["msedgedriver.exe", "msedgedriver"]).

    Returns:
        str | None: Absolute path to the first matching binary, or None if
                    none were found in either location.
    """
    # 1. Try the system PATH first (the normal, preferred approach)
    for name in names:
        path = shutil.which(name)  # Returns None if the binary isn't on PATH
        if path:
            return path

    # 2. Fall back to the hardcoded list for environments without PATH access
    for known_path in KNOWN_DRIVER_PATHS:
        for name in names:
            # Match by filename (case-insensitive) and confirm the file exists
            if os.path.basename(known_path).lower() == name.lower() and os.path.isfile(known_path):
                return known_path

    return None  # Driver not found anywhere


def get_driver():
    """
    Attempt to create a headless Selenium WebDriver instance.

    Tries Edge, Chrome, and Firefox in that order. For each browser,
    local_driver_path() first checks the system PATH, then the
    KNOWN_DRIVER_PATHS fallback list, so this works even without admin rights.

    Returns:
        selenium.webdriver.*: A configured, headless browser driver, OR
        str: An error message if no suitable browser/driver combo was found.
    """
    # Each entry: (display name, Service class, Driver class, binary names, Options class)
    drivers = [
        ("Edge",    EdgeService,    webdriver.Edge,    ["msedgedriver.exe", "msedgedriver"], webdriver.EdgeOptions),
        ("Chrome",  ChromeService,  webdriver.Chrome,  ["chromedriver.exe", "chromedriver"],  webdriver.ChromeOptions),
        ("Firefox", FirefoxService, webdriver.Firefox, ["geckodriver.exe",  "geckodriver"],   webdriver.FirefoxOptions),
    ]

    for name, service_cls, driver_cls, executable_names, options_cls in drivers:
        driver_path = local_driver_path(executable_names)
        if not driver_path:
            continue  # This browser's driver isn't installed; try the next one

        try:
            options = options_cls()
            options.add_argument("--headless")            # Run without a visible window
            options.add_argument("--disable-gpu")         # Required on some Windows systems
            options.add_argument("--no-sandbox")          # Needed in restricted/container environments
            options.add_argument("--disable-dev-shm-usage")  # Avoid shared-memory issues in Docker

            # Firefox uses a keyword argument; Chrome/Edge use a positional argument
            service = service_cls(driver_path) if name != "Firefox" else service_cls(executable_path=driver_path)
            return driver_cls(service=service, options=options)
        except Exception:
            continue  # Driver found but failed to launch; try the next browser

    # No browser/driver combo worked
    return "Please install Chrome, Firefox, or Edge and make sure the corresponding webdriver binary is available on PATH."


# ---------------------------------------------------------------------------
# Scraping logic
# ---------------------------------------------------------------------------

def scrape_jobs(search_term, location):
    """
    Scrape job listings from three sources: hu.indeed.com, LinkedIn, and prof.hu.

    Up to 5 job cards are collected from each site. Any card that can't be
    parsed (missing element, stale reference, etc.) is silently skipped.

    Args:
        search_term (str): Keywords to search for (e.g. "SAP SuccessFactor").
        location    (str): Target location (e.g. "Budapest").

    Returns:
        list[tuple] | str:
            On success – list of (title, company, location, link, search_label) tuples.
            On failure – error string from get_driver() if no browser is available.
    """
    driver = get_driver()
    if isinstance(driver, str):
        # get_driver() returned an error message instead of a driver object
        return driver

    jobs = []
    try:
        # ── Indeed Hungary ────────────────────────────────────────────────────
        driver.get(f"https://hu.indeed.com/jobs?q={search_term}&l={location}")
        time.sleep(2)  # Wait for the page's JavaScript to finish rendering

        job_cards = driver.find_elements(By.CLASS_NAME, 'job_seen_beacon')
        for card in job_cards[:5]:  # Limit to the first 5 results
            try:
                title   = card.find_element(By.CLASS_NAME, 'jobTitle').text
                company = card.find_element(By.CLASS_NAME, 'companyName').text
                loc     = card.find_element(By.CLASS_NAME, 'companyLocation').text
                link    = card.find_element(By.TAG_NAME,   'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue  # Skip cards with missing/unexpected HTML structure

        # ── LinkedIn ─────────────────────────────────────────────────────────
        driver.get(f"https://www.linkedin.com/jobs/search/?keywords={search_term}&location={location}")
        time.sleep(2)

        job_cards = driver.find_elements(By.CLASS_NAME, 'job-search-card')
        for card in job_cards[:5]:
            try:
                title   = card.find_element(By.CLASS_NAME, 'job-search-card__title').text
                company = card.find_element(By.CLASS_NAME, 'job-search-card__subtitle').text
                loc     = card.find_element(By.CLASS_NAME, 'job-search-card__location').text
                link    = card.find_element(By.TAG_NAME,   'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue

        # ── prof.hu ──────────────────────────────────────────────────────────
        # prof.hu uses hyphenated slugs in the URL path for the search term
        driver.get(f"https://www.prof.hu/allasok/{search_term.replace(' ', '-')}/hely-{location}")
        time.sleep(2)

        job_cards = driver.find_elements(By.CLASS_NAME, 'job-item')
        for card in job_cards[:5]:
            try:
                title   = card.find_element(By.TAG_NAME,   'h2').text
                company = card.find_element(By.CLASS_NAME, 'company').text
                loc     = location  # prof.hu doesn't expose a per-card location element
                link    = card.find_element(By.TAG_NAME,   'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue

    finally:
        driver.quit()  # Always close the browser, even if an exception occurred

    return jobs


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    """
    Main dashboard route.

    GET  – renders the job table with all stored results.
    POST – handles two form actions:
        'scrape': kicks off a new scrape and saves results to the DB.
        'clear':  deletes all stored jobs.

    After a successful POST action the user is redirected back to GET
    (Post/Redirect/Get pattern) to prevent duplicate submissions on refresh.
    """
    error = None

    if request.method == 'POST':
        if 'scrape' in request.form:
            # Read form inputs; fall back to sensible defaults
            search_term = request.form.get('search_term', 'SAP SuccessFactor')
            location    = request.form.get('location',    'Budapest')

            result = scrape_jobs(search_term, location)

            if isinstance(result, str):
                # scrape_jobs returned an error message (no browser available)
                error = result
            else:
                # Persist each scraped job to the database
                for job in result:
                    save_job(*job)
                return redirect(url_for('dashboard'))

        elif 'clear' in request.form:
            clear_all_jobs()
            return redirect(url_for('dashboard'))

    # Fetch all jobs for display (newest first)
    jobs = get_all_jobs()

    # ── HTML template (inline) ────────────────────────────────────────────
    # Built as a plain string so the file stays self-contained (no templates dir).
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Job Scraper Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .container { max-width: 1000px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            form { margin-bottom: 20px; }
            input, button { padding: 10px; margin: 5px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #4CAF50; color: white; }
            tr:hover { background-color: #f5f5f5; }
            .hot { color: red; font-weight: bold; }
            .button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; }
            .button:hover { background-color: #45a049; }
            .delete { background-color: #f44336; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Job Scraper Dashboard</h1>
            ''' + (f'<p class="error">{error}</p>' if error else '') + '''
            <form method="post">
                <input type="text" name="search_term" placeholder="Search term (e.g., SAP SuccessFactor)" value="SAP SuccessFactor">
                <input type="text" name="location" placeholder="Location (e.g., Budapest)" value="Budapest">
                <button type="submit" name="scrape" class="button">Scrape Jobs</button>
                <button type="submit" name="clear" class="button delete">Clear All Jobs</button>
            </form>
            <p>Total jobs: <strong>''' + str(len(jobs)) + '''</strong></p>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Company</th>
                    <th>Location</th>
                    <th>Link</th>
                    <th>Search Term</th>
                    <th>Timestamp</th>
                    <th>HOT</th>
                    <th>Actions</th>
                </tr>
    '''

    # Render one table row per job record
    for row in jobs:
        # row indices: 0=id, 1=title, 2=company, 3=location, 4=link,
        #              5=search_term, 6=timestamp, 7=hot_flag
        hot_class = 'hot' if row[7] else ''  # Apply red styling to HOT jobs
        html += f'''
        <tr>
            <td>{row[0]}</td>
            <td>{row[1]}</td>
            <td>{row[2]}</td>
            <td>{row[3]}</td>
            <td><a href="{row[4]}" target="_blank">Open</a></td>
            <td>{row[5]}</td>
            <td>{row[6]}</td>
            <td class="{hot_class}">{ 'Yes' if row[7] else 'No' }</td>
            <td>
                <!-- Toggle HOT status for this job -->
                <form action="/toggle_hot" method="post" style="display:inline;">
                    <input type="hidden" name="job_id" value="{row[0]}">
                    <button type="submit" class="button">Toggle HOT</button>
                </form>
                <!-- Permanently delete this job -->
                <form action="/delete" method="post" style="display:inline;">
                    <input type="hidden" name="job_id" value="{row[0]}">
                    <button type="submit" class="button delete">Delete</button>
                </form>
            </td>
        </tr>
        '''

    html += '''
            </table>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html)


@app.route('/toggle_hot', methods=['POST'])
def toggle_hot():
    """
    Flip the hot_flag for a job.

    Reads the current flag from the in-memory job list and sets it to the
    opposite value (0 → 1, 1 → 0), then persists the change.

    Expects form field:
        job_id (int): ID of the job to toggle.
    """
    job_id = int(request.form['job_id'])
    current_jobs = get_all_jobs()

    # If the job is NOT currently flagged as hot, flag it; otherwise un-flag it
    hot_flag = 1 if not any(r[0] == job_id and r[7] for r in current_jobs) else 0

    update_hot_flag(job_id, hot_flag)
    return redirect(url_for('dashboard'))


@app.route('/delete', methods=['POST'])
def delete():
    """
    Delete a single job from the database.

    Expects form field:
        job_id (int): ID of the job to remove.
    """
    job_id = request.form['job_id']
    delete_job(job_id)
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Ensure the database table exists before starting the server
    create_table()

    print("\n" + "="*50)
    print("Job Scraper Web Server")
    print("="*50)
    print("Dashboard: http://127.0.0.1:5000")
    print("Press Ctrl+C to stop the server")
    print("="*50 + "\n")

    # Start the Flask development server (localhost only, debug mode on)
    # NOTE: debug=True auto-reloads on code changes but should be disabled in production
    app.run(host='127.0.0.1', port=5000, debug=True)