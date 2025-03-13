import sqlite3


def get_db_connection():
    """Har bir so‘rov uchun yangi ulanish yaratish."""
    return sqlite3.connect('users.db')


def get_total_users():
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]    

def get_monthly_users():
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE datetime(registered_at) >= datetime('now', '-30 days')
        """)
        return cursor.fetchone()[0]
    
def get_daily_users():
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE datetime(registered_at) >= datetime('now', '-1 day')
        """)
        return cursor.fetchone()[0]
