import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatbot.db")
print("DB path:", db_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(users)")
cols = cursor.fetchall()
col_names = [c[1] for c in cols]
print("Current columns:", col_names)

changed = False

if "hashed_password" not in col_names:
    cursor.execute('ALTER TABLE users ADD COLUMN hashed_password TEXT NOT NULL DEFAULT ""')
    print("Added hashed_password column")
    changed = True
else:
    print("hashed_password already exists")

if "name" not in col_names:
    cursor.execute("ALTER TABLE users ADD COLUMN name TEXT")
    print("Added name column")
    changed = True
else:
    print("name already exists")

if "created_at" not in col_names:
    cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    print("Added created_at column")
    changed = True
else:
    print("created_at already exists")

if changed:
    conn.commit()

conn.close()
print("Migration complete.")
