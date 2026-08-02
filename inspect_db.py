import os
import sqlite3
import re
from dotenv import load_dotenv

def inspect_postgresql():
    print("=== INSPECTING POSTGRESQL DATABASE ===")
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        print(f".env file not found at {env_path}")
        return
        
    load_dotenv(env_path, override=True)
    
    db_url = os.environ.get("DATABASE_URL")
    if not db_url or "HOST" in db_url or "USER:PASSWORD" in db_url:
        db_url = os.environ.get("Internal_Database_URL")
        
    if not db_url:
        print("DATABASE_URL or Internal_Database_URL not found in .env file.")
        return
        
    db_url = db_url.strip('"').strip("'")
    
    # If running locally and internal URL is set, swap it to the external host
    if "@dpg-" in db_url and ".render.com" not in db_url:
        db_url = re.sub(r'(@dpg-[^/]+)', r'\1.oregon-postgres.render.com', db_url)
        
    print(f"Database DSN host: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    
    try:
        import sys
        # Reconfigure stdout to use utf-8 if supported (Python 3.7+)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
        
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Get list of user-defined tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [t[0] for t in cursor.fetchall()]
        print(f"Tables found in PostgreSQL: {tables}")
        
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"\n- Table '{table}' has {count} row(s):")
            
            # Print column names in correct database order
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = %s 
                ORDER BY ordinal_position
            """, (table,))
            cols = [c[0] for c in cursor.fetchall()]
            print(f"  Columns: {', '.join(cols)}")
            
            # Print sample rows
            cursor.execute(f"SELECT * FROM {table} LIMIT 5")
            rows = cursor.fetchall()
            if rows:
                print("  Sample rows (up to 5):")
                for row in rows:
                    # Print as dict-like matching column to value
                    row_dict = dict(zip(cols, row))
                    # Avoid printing complete password hashes or secrets in terminal output directly if possible
                    if 'hashed_password' in row_dict:
                        row_dict['hashed_password'] = '[HIDDEN]'
                    try:
                        print("   ", row_dict)
                    except UnicodeEncodeError:
                        # Fallback for terminals that don't support unicode
                        print("   ", {k: str(v).encode('ascii', 'replace').decode('ascii') for k, v in row_dict.items()})
            else:
                print("    (Empty table)")
                
        conn.close()
    except ImportError:
        print("psycopg2 is not installed in the current Python environment.")
        print("Install it with: pip install psycopg2-binary")
        print(f"Connection URL you can copy to a database client like DBeaver/TablePlus:\n{db_url}")
    except Exception as e:
        print(f"Failed to connect or query PostgreSQL: {e}")

def inspect_sqlite():
    print("\n=== INSPECTING LOCAL SQLITE DATABASE ===")
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatbot.db")
    if not os.path.exists(db_path):
        print(f"chatbot.db does not exist in root folder ({db_path}).")
        return
        
    print(f"Connecting to SQLite database: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"Tables found in SQLite: {tables}")
        
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"\n- Table '{table}' has {count} row(s):")
            
            # Get table info (columns)
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [c[1] for c in cursor.fetchall()]
            print(f"  Columns: {', '.join(cols)}")
            
            cursor.execute(f"SELECT * FROM {table} LIMIT 5")
            rows = cursor.fetchall()
            if rows:
                print("  Sample rows (up to 5):")
                for row in rows:
                    row_dict = dict(zip(cols, row))
                    if 'hashed_password' in row_dict:
                        row_dict['hashed_password'] = '[HIDDEN]'
                    try:
                        print("   ", row_dict)
                    except UnicodeEncodeError:
                        print("   ", {k: str(v).encode('ascii', 'replace').decode('ascii') for k, v in row_dict.items()})
            else:
                print("    (Empty table)")
                    
        conn.close()
    except Exception as e:
        print(f"Failed to connect or query SQLite: {e}")

if __name__ == "__main__":
    inspect_postgresql()
    inspect_sqlite()
