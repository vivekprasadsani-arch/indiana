#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Bot Starter - Uses PostgreSQL (Supabase)
This is a simpler approach that directly runs the bot with PostgreSQL
"""

import os
import sys

# Check DATABASE_URL
if not os.getenv("DATABASE_URL"):
    print("ERROR: DATABASE_URL not set!")
    print("This is for production. For local development, use: python telegram_bot.py")
    sys.exit(1)

print("[*] Production mode - Using PostgreSQL")
print(f"[*] DATABASE_URL: {os.getenv('DATABASE_URL')[:30]}...")

# Now modify telegram_bot to use PostgreSQL
import telegram_bot

# Replace SQLite functions with PostgreSQL functions
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as pg_pool
from datetime import datetime
import pytz

DATABASE_URL = os.getenv("DATABASE_URL")
BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')

# Global connection pool
db_pool = None

def init_pg_pool():
    """Initialize PostgreSQL connection pool"""
    global db_pool
    try:
        db_pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=DATABASE_URL
        )
        print("[OK] PostgreSQL connection pool initialized")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to initialize database pool: {e}")
        return False

def get_pg_connection():
    """Get connection from pool"""
    if db_pool:
        return db_pool.getconn()
    return None

def return_pg_connection(conn):
    """Return connection to pool"""
    if db_pool and conn:
        db_pool.putconn(conn)

# PostgreSQL version of database functions
def pg_get_user(user_id: int):
    """Get user from PostgreSQL"""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"Error getting user: {e}")
        return None
    finally:
        return_pg_connection(conn)

def pg_add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
    """Add/update user in PostgreSQL"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, approved)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT (user_id) 
            DO UPDATE SET username = %s, first_name = %s, last_name = %s
        ''', (user_id, username, first_name, last_name, username, first_name, last_name))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error adding/updating user: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_approve_user(user_id: int):
    """Approve user"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET approved = 1 WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error approving user: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_reject_user(user_id: int):
    """Reject user"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET approved = -1 WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error rejecting user: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_update_user_stats(user_id: int, numbers_added: int = 0, earnings: float = 0):
    """Update user statistics"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET total_numbers = total_numbers + %s,
                daily_numbers = daily_numbers + %s,
                balance = balance + %s
            WHERE user_id = %s
        ''', (numbers_added, numbers_added, earnings, user_id))
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        cursor.execute('''
            INSERT INTO daily_stats (user_id, date, numbers_added, earnings)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                numbers_added = daily_stats.numbers_added + %s,
                earnings = daily_stats.earnings + %s
        ''', (user_id, today, numbers_added, earnings, numbers_added, earnings))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error updating user stats: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_reset_daily_stats():
    """Reset daily stats"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET daily_numbers = 0')
        cursor.execute('DELETE FROM number_progress WHERE completed = 0')
        conn.commit()
        cursor.close()
        print("[OK] Daily stats reset completed")
    except Exception as e:
        print(f"Error resetting daily stats: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_get_daily_report():
    """Get daily report"""
    conn = get_pg_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT u.user_id, u.first_name, u.username, 
                   COALESCE(d.numbers_added, 0) as numbers_added, 
                   COALESCE(d.earnings, 0) as earnings
            FROM users u
            LEFT JOIN daily_stats d ON u.user_id = d.user_id AND d.date = %s
            WHERE u.approved = 1
            ORDER BY d.numbers_added DESC NULLS LAST
        ''', (today,))
        rows = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error getting daily report: {e}")
        return []
    finally:
        return_pg_connection(conn)

def pg_log_activity(user_id: int, action: str, details: str = ""):
    """Log activity"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activity_log (user_id, action, details)
            VALUES (%s, %s, %s)
        ''', (user_id, action, details))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error logging activity: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_get_number_progress(phone: str):
    """Get number progress"""
    conn = get_pg_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM number_progress WHERE phone_number = %s', (phone,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {
                'phone_number': row['phone_number'],
                'user_id': row['user_id'],
                'site1_linked': bool(row['site1_linked']),
                'site2_linked': bool(row['site2_linked']),
                'site3_linked': bool(row['site3_linked']),
                'site4_linked': bool(row['site4_linked']),
                'completed': bool(row['completed']),
                'created_at': row['created_at'],
                'last_updated': row['last_updated']
            }
        return None
    except Exception as e:
        print(f"Error getting number progress: {e}")
        return None
    finally:
        return_pg_connection(conn)

def pg_init_number_progress(phone: str, user_id: int):
    """Init number progress"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO number_progress (phone_number, user_id)
            VALUES (%s, %s)
            ON CONFLICT (phone_number) DO NOTHING
        ''', (phone, user_id))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error initializing number progress: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_update_site_progress(phone: str, site_index: int, linked: bool = True):
    """Update site progress"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        site_column = f'site{site_index}_linked'
        query = f'''
            UPDATE number_progress
            SET {site_column} = %s, last_updated = CURRENT_TIMESTAMP
            WHERE phone_number = %s
        '''
        cursor.execute(query, (1 if linked else 0, phone))
        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Error updating site progress: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

def pg_check_and_complete_number(phone: str):
    """Check and complete number"""
    conn = get_pg_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT site1_linked, site2_linked, site3_linked, site4_linked
            FROM number_progress WHERE phone_number = %s
        ''', (phone,))
        row = cursor.fetchone()
        if row and all(row):
            cursor.execute('''
                UPDATE number_progress
                SET completed = 1, last_updated = CURRENT_TIMESTAMP
                WHERE phone_number = %s
            ''', (phone,))
            conn.commit()
            cursor.close()
            return True
        cursor.close()
        return False
    except Exception as e:
        print(f"Error checking completion: {e}")
        conn.rollback()
        return False
    finally:
        return_pg_connection(conn)

def pg_get_incomplete_sites(phone: str):
    """Get incomplete sites"""
    progress = pg_get_number_progress(phone)
    if not progress:
        return [1, 2, 3, 4]
    incomplete = []
    for i in range(1, 5):
        if not progress[f'site{i}_linked']:
            incomplete.append(i)
    return incomplete

def pg_reset_daily_number_progress():
    """Reset daily number progress"""
    conn = get_pg_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM number_progress WHERE completed = 0')
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        print(f"[OK] Deleted {deleted_count} incomplete number progress records")
    except Exception as e:
        print(f"Error resetting number progress: {e}")
        conn.rollback()
    finally:
        return_pg_connection(conn)

# Initialize PostgreSQL
print("[*] Initializing PostgreSQL...")
if not init_pg_pool():
    print("[ERROR] Failed to initialize PostgreSQL!")
    sys.exit(1)

# Override database functions in telegram_bot module
telegram_bot.get_user = pg_get_user
telegram_bot.add_or_update_user = pg_add_or_update_user
telegram_bot.approve_user = pg_approve_user
telegram_bot.reject_user = pg_reject_user
telegram_bot.update_user_stats = pg_update_user_stats
telegram_bot.reset_daily_stats = pg_reset_daily_stats
telegram_bot.get_daily_report = pg_get_daily_report
telegram_bot.log_activity = pg_log_activity
telegram_bot.get_number_progress = pg_get_number_progress
telegram_bot.init_number_progress = pg_init_number_progress
telegram_bot.update_site_progress = pg_update_site_progress
telegram_bot.check_and_complete_number = pg_check_and_complete_number
telegram_bot.get_incomplete_sites = pg_get_incomplete_sites
telegram_bot.reset_daily_number_progress = pg_reset_daily_number_progress

# Override init_db to do nothing (already initialized)
telegram_bot.init_db = lambda: print("[OK] Database already initialized")

print("[OK] PostgreSQL functions injected")
print("[OK] Starting bot with PostgreSQL backend...\n")

# Start the bot
if __name__ == '__main__':
    telegram_bot.main()

