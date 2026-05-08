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

# Database setup
DB_NAME = 'jobs.db'

# Flask app
app = Flask(__name__)

def create_table():
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    cursor.execute(
        'INSERT INTO jobs (title, company, location, link, search_term, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (title, company, location, link, search_term, timestamp)
    )
    conn.commit()
    conn.close()

def get_all_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, company, location, link, search_term, timestamp, hot_flag FROM jobs ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_hot_flag(job_id, hot_flag):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE jobs SET hot_flag = ? WHERE id = ?', (hot_flag, job_id))
    conn.commit()
    conn.close()

def delete_job(job_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()

def clear_all_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM jobs')
    conn.commit()
    conn.close()

def local_driver_path(names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None

def get_driver():
    drivers = [
        ("Edge", EdgeService, webdriver.Edge, ["msedgedriver.exe", "msedgedriver"], webdriver.EdgeOptions),
        ("Chrome", ChromeService, webdriver.Chrome, ["chromedriver.exe", "chromedriver"], webdriver.ChromeOptions),
        ("Firefox", FirefoxService, webdriver.Firefox, ["geckodriver.exe", "geckodriver"], webdriver.FirefoxOptions),
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
            service = service_cls(driver_path) if name != "Firefox" else service_cls(executable_path=driver_path)
            return driver_cls(service=service, options=options)
        except Exception:
            continue

    return "Please install Chrome, Firefox, or Edge and make sure the corresponding webdriver binary is available on PATH."

def scrape_jobs(search_term, location):
    driver = get_driver()
    if isinstance(driver, str):
        return driver

    jobs = []
    try:
        driver.get(f"https://hu.indeed.com/jobs?q={search_term}&l={location}")
        time.sleep(2)
        job_cards = driver.find_elements(By.CLASS_NAME, 'job_seen_beacon')
        for card in job_cards[:5]:
            try:
                title = card.find_element(By.CLASS_NAME, 'jobTitle').text
                company = card.find_element(By.CLASS_NAME, 'companyName').text
                loc = card.find_element(By.CLASS_NAME, 'companyLocation').text
                link = card.find_element(By.TAG_NAME, 'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue

        driver.get(f"https://www.linkedin.com/jobs/search/?keywords={search_term}&location={location}")
        time.sleep(2)
        job_cards = driver.find_elements(By.CLASS_NAME, 'job-search-card')
        for card in job_cards[:5]:
            try:
                title = card.find_element(By.CLASS_NAME, 'job-search-card__title').text
                company = card.find_element(By.CLASS_NAME, 'job-search-card__subtitle').text
                loc = card.find_element(By.CLASS_NAME, 'job-search-card__location').text
                link = card.find_element(By.TAG_NAME, 'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue

        driver.get(f"https://www.prof.hu/allasok/{search_term.replace(' ', '-')}/hely-{location}")
        time.sleep(2)
        job_cards = driver.find_elements(By.CLASS_NAME, 'job-item')
        for card in job_cards[:5]:
            try:
                title = card.find_element(By.TAG_NAME, 'h2').text
                company = card.find_element(By.CLASS_NAME, 'company').text
                loc = location
                link = card.find_element(By.TAG_NAME, 'a').get_attribute('href')
                jobs.append((title, company, loc, link, f"{search_term} in {location}"))
            except Exception:
                continue
    finally:
        driver.quit()

    return jobs

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    error = None
    if request.method == 'POST':
        if 'scrape' in request.form:
            search_term = request.form.get('search_term', 'SAP SuccessFactor')
            location = request.form.get('location', 'Budapest')
            result = scrape_jobs(search_term, location)
            if isinstance(result, str):
                error = result
            else:
                for job in result:
                    save_job(*job)
                return redirect(url_for('dashboard'))
        elif 'clear' in request.form:
            clear_all_jobs()
            return redirect(url_for('dashboard'))

    jobs = get_all_jobs()
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
    for row in jobs:
        hot_class = 'hot' if row[7] else ''
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
    job_id = int(request.form['job_id'])
    current_hot = get_all_jobs()
    hot_flag = 1 if not any(r[0] == job_id and r[7] for r in current_hot) else 0
    update_hot_flag(job_id, hot_flag)
    return redirect(url_for('dashboard'))

@app.route('/delete', methods=['POST'])
def delete():
    job_id = request.form['job_id']
    delete_job(job_id)
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    create_table()
    print("\n" + "="*50)
    print("Job Scraper Web Server")
    print("="*50)
    print("Dashboard: http://127.0.0.1:5000")
    print("Press Ctrl+C to stop the server")
    print("="*50 + "\n")
    app.run(host='127.0.0.1', port=5000, debug=True)