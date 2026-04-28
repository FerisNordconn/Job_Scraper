import sqlite3
from datetime import datetime

# Database setup
DB_NAME = 'jobs.db'

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

if __name__ == '__main__':
    create_table()
    today = datetime.today()
    weekday = today.strftime("%A")
    save_weekday(weekday)