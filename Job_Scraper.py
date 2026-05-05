import sqlite3
from datetime import datetime
from flask import Flask, render_template_string

# Database setup
DB_NAME = 'jobs.db'

# Flask app
app = Flask(__name__)

def create_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weekdays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_weekday(weekday):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    cursor.execute('INSERT INTO weekdays (weekday, timestamp) VALUES (?, ?)',
                   (weekday, timestamp))
    conn.commit()
    conn.close()
    print(f"Saved weekday: {weekday} at {timestamp}")

def get_all_weekdays():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, weekday, timestamp FROM weekdays ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

@app.route('/')
def dashboard():
    weekdays = get_all_weekdays()
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Job Scraper Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #4CAF50; color: white; }
            tr:hover { background-color: #f5f5f5; }
            .button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin-top: 20px; }
            .button:hover { background-color: #45a049; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Job Scraper Dashboard</h1>
            <p>Database: <strong>''' + DB_NAME + '''</strong></p>
            <p>Total entries: <strong>''' + str(len(weekdays)) + '''</strong></p>
            
            <h2>Recent Entries</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Weekday</th>
                    <th>Timestamp</th>
                </tr>
    '''
    
    if weekdays:
        for row in weekdays:
            html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td></tr>"
    else:
        html += "<tr><td colspan='3'>No data yet. Run the scraper to populate the database.</td></tr>"
    
    html += '''
            </table>
            <p><small>Refresh the page to see updated data.</small></p>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html)

if __name__ == '__main__':
    create_table()
    
    # Save today's weekday
    today = datetime.today()
    weekday = today.strftime("%A")
    save_weekday(weekday)
    
    # Run Flask web server on 127.0.0.1:5000
    print("\n" + "="*50)
    print("Job Scraper Web Server")
    print("="*50)
    print("Dashboard: http://127.0.0.1:5000")
    print("Press Ctrl+C to stop the server")
    print("="*50 + "\n")
    
    app.run(host='127.0.0.1', port=5000, debug=True)