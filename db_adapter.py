#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Adapter - Automatically uses SQLite or PostgreSQL based on DATABASE_URL
This allows telegram_bot.py to work unchanged in both local and production
"""

import os
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Check if we should use PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")
# Fix password encoding if @ symbol is present (URL encode @ to %40)
if DATABASE_URL and '@' in DATABASE_URL:
    # Check if password contains @ that needs encoding
    # Format: postgresql://user:password@host:port/db
    try:
        from urllib.parse import urlparse, urlunparse, quote
        parsed = urlparse(DATABASE_URL)
        if '@' in parsed.netloc:
            # Split netloc to get user:pass and host:port
            auth_part, host_part = parsed.netloc.rsplit('@', 1)
            if ':' in auth_part:
                user, password = auth_part.split(':', 1)
                # Only encode if password has @ and not already encoded
                if '@' in password and '%40' not in password:
                    password = password.replace('@', '%40')
                    auth_part = f"{user}:{password}"
                    parsed = parsed._replace(netloc=f"{auth_part}@{host_part}")
                    DATABASE_URL = urlunparse(parsed)
                    logger.info("Fixed DATABASE_URL password encoding")
    except Exception as e:
        logger.warning(f"Could not fix DATABASE_URL encoding: {e}")

USE_POSTGRES = bool(DATABASE_URL)

# Initialize based on database type
if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from psycopg2 import pool as pg_pool
        import pytz
        from datetime import datetime
        
        # Force IPv4 connection (fix IPv6 unreachable issue)
        # Parse and modify connection string to prefer IPv4
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(DATABASE_URL)
            # Add connect_timeout and prefer IPv4
            if '?' in DATABASE_URL:
                # Already has query params
                if 'prefer_simple_protocol' not in parsed.query:
                    DATABASE_URL = f"{DATABASE_URL}&connect_timeout=10"
            else:
                DATABASE_URL = f"{DATABASE_URL}?connect_timeout=10"
        except Exception as e:
            logger.warning(f"Could not modify DATABASE_URL: {e}")
        
        # Create connection pool with IPv4 preference
        try:
            db_pool = pg_pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
            # Test connection
            test_conn = db_pool.getconn()
            test_conn.close()
            db_pool.putconn(test_conn)
            logger.info("Using PostgreSQL database (connection successful)")
        except Exception as e:
            logger.error(f"PostgreSQL connection pool failed: {e}")
            raise
        
        def get_connection():
            return db_pool.getconn()
        
        def return_connection(conn):
            db_pool.putconn(conn)
        
        def execute_query(query, params=(), fetch=None):
            """Execute PostgreSQL query"""
            conn = get_connection()
            try:
                if fetch == 'dict':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                else:
                    cursor = conn.cursor()
                
                cursor.execute(query, params)
                
                if fetch == 'one':
                    result = cursor.fetchone()
                elif fetch == 'all':
                    result = cursor.fetchall()
                elif fetch == 'dict':
                    result = cursor.fetchone()
                    result = dict(result) if result else None
                else:
                    result = None
                
                conn.commit()
                cursor.close()
                return result
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error: {e}")
                return None if fetch else False
            finally:
                return_connection(conn)
        
    except Exception as e:
        logger.error(f"PostgreSQL initialization failed: {e}")
        USE_POSTGRES = False

# SQLite implementation (default)
if not USE_POSTGRES:
    import sqlite3
    DB_PATH = "telegram_bot.db"
    logger.info("Using SQLite database")
    
    def get_connection():
        return sqlite3.connect(DB_PATH, check_same_thread=False)
    
    def return_connection(conn):
        conn.close()
    
    def execute_query(query, params=(), fetch=None):
        """Execute SQLite query"""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if fetch == 'one':
                result = cursor.fetchone()
            elif fetch == 'all':
                result = cursor.fetchall()
            elif fetch == 'dict':
                # SQLite doesn't have RealDictCursor, convert manually
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    result = dict(zip(columns, row))
                else:
                    result = None
            else:
                result = None
            
            conn.commit()
            cursor.close()
            return result
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            return None if fetch else False
        finally:
            return_connection(conn)

# Database functions that work with both SQLite and PostgreSQL
def init_db():
    """Initialize database - creates tables if using SQLite, skips if PostgreSQL"""
    if USE_POSTGRES:
        logger.info("PostgreSQL database - tables should already exist in Supabase")
        return
    
    # SQLite - create tables
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            approved INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            total_numbers INTEGER DEFAULT 0,
            daily_numbers INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS number_progress (
            phone_number TEXT PRIMARY KEY,
            user_id INTEGER,
            site1_linked INTEGER DEFAULT 0,
            site2_linked INTEGER DEFAULT 0,
            site3_linked INTEGER DEFAULT 0,
            site4_linked INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            numbers_added INTEGER DEFAULT 0,
            earnings REAL DEFAULT 0,
            UNIQUE(user_id, date)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            site_key TEXT PRIMARY KEY,
            token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    cursor.close()
    return_connection(conn)
    logger.info("SQLite database initialized")

def get_user(user_id: int) -> Optional[Dict]:
    """Get user from database"""
    if USE_POSTGRES:
        row = execute_query('SELECT * FROM users WHERE user_id = %s', (user_id,), fetch='dict')
        return row
    else:
        row = execute_query('SELECT * FROM users WHERE user_id = ?', (user_id,), fetch='dict')
        if row:
            return {
                'user_id': row['user_id'],
                'username': row['username'],
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'approved': row['approved'],
                'balance': row['balance'],
                'total_numbers': row['total_numbers'],
                'daily_numbers': row['daily_numbers'],
                'joined_at': row['joined_at']
            }
        return None

def add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
    """Add or update user"""
    if USE_POSTGRES:
        execute_query('''
            INSERT INTO users (user_id, username, first_name, last_name, approved)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT (user_id) DO UPDATE SET username = %s, first_name = %s, last_name = %s
        ''', (user_id, username, first_name, last_name, username, first_name, last_name))
    else:
        execute_query('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, approved)
            VALUES (?, ?, ?, ?, COALESCE((SELECT approved FROM users WHERE user_id = ?), 0))
        ''', (user_id, username, first_name, last_name, user_id))

def approve_user(user_id: int):
    """Approve user"""
    if USE_POSTGRES:
        execute_query('UPDATE users SET approved = 1 WHERE user_id = %s', (user_id,))
    else:
        execute_query('UPDATE users SET approved = 1 WHERE user_id = ?', (user_id,))

def reject_user(user_id: int):
    """Reject user"""
    if USE_POSTGRES:
        execute_query('UPDATE users SET approved = -1 WHERE user_id = %s', (user_id,))
    else:
        execute_query('UPDATE users SET approved = -1 WHERE user_id = ?', (user_id,))

def update_user_stats(user_id: int, numbers_added: int = 0, earnings: float = 0):
    """Update user statistics"""
    if USE_POSTGRES:
        execute_query('''
            UPDATE users 
            SET total_numbers = total_numbers + %s,
                daily_numbers = daily_numbers + %s,
                balance = balance + %s
            WHERE user_id = %s
        ''', (numbers_added, numbers_added, earnings, user_id))
        
        from datetime import datetime
        import pytz
        BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        execute_query('''
            INSERT INTO daily_stats (user_id, date, numbers_added, earnings)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                numbers_added = daily_stats.numbers_added + %s,
                earnings = daily_stats.earnings + %s
        ''', (user_id, today, numbers_added, earnings, numbers_added, earnings))
    else:
        execute_query('''
            UPDATE users 
            SET total_numbers = total_numbers + ?,
                daily_numbers = daily_numbers + ?,
                balance = balance + ?
            WHERE user_id = ?
        ''', (numbers_added, numbers_added, earnings, user_id))
        
        from datetime import datetime
        import pytz
        BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        execute_query('''
            INSERT INTO daily_stats (user_id, date, numbers_added, earnings)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                numbers_added = numbers_added + ?,
                earnings = earnings + ?
        ''', (user_id, today, numbers_added, earnings, numbers_added, earnings))

def reset_daily_stats():
    """Reset daily statistics"""
    if USE_POSTGRES:
        execute_query('UPDATE users SET daily_numbers = 0')
        execute_query('DELETE FROM number_progress WHERE completed = 0')
    else:
        execute_query('UPDATE users SET daily_numbers = 0')
        execute_query('DELETE FROM number_progress WHERE completed = 0')
    logger.info("Daily stats reset completed")

def get_daily_report() -> List[Dict]:
    """Get daily report"""
    from datetime import datetime
    import pytz
    BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')
    today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
    
    if USE_POSTGRES:
        rows = execute_query('''
            SELECT u.user_id, u.first_name, u.username,
                   COALESCE(d.numbers_added, 0) as numbers_added,
                   COALESCE(d.earnings, 0) as earnings
            FROM users u
            LEFT JOIN daily_stats d ON u.user_id = d.user_id AND d.date = %s
            WHERE u.approved = 1
            ORDER BY d.numbers_added DESC NULLS LAST
        ''', (today,), fetch='all')
        return [dict(row) for row in rows] if rows else []
    else:
        rows = execute_query('''
            SELECT u.user_id, u.first_name, u.username, d.numbers_added, d.earnings
            FROM users u
            LEFT JOIN daily_stats d ON u.user_id = d.user_id AND d.date = ?
            WHERE u.approved = 1 AND (d.numbers_added > 0 OR d.numbers_added IS NULL)
            ORDER BY d.numbers_added DESC
        ''', (today,), fetch='all')
        if rows:
            columns = ['user_id', 'first_name', 'username', 'numbers_added', 'earnings']
            return [dict(zip(columns, row)) for row in rows]
        return []

def log_activity(user_id: int, action: str, details: str = ""):
    """Log user activity"""
    if USE_POSTGRES:
        execute_query('INSERT INTO activity_log (user_id, action, details) VALUES (%s, %s, %s)',
                     (user_id, action, details))
    else:
        execute_query('INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)',
                     (user_id, action, details))

def get_number_progress(phone: str):
    """Get progress for a phone number"""
    if USE_POSTGRES:
        row = execute_query('SELECT * FROM number_progress WHERE phone_number = %s', (phone,), fetch='dict')
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
    else:
        row = execute_query('SELECT * FROM number_progress WHERE phone_number = ?', (phone,), fetch='dict')
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

def init_number_progress(phone: str, user_id: int):
    """Initialize progress tracking"""
    if USE_POSTGRES:
        execute_query('INSERT INTO number_progress (phone_number, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                     (phone, user_id))
    else:
        execute_query('INSERT OR IGNORE INTO number_progress (phone_number, user_id) VALUES (?, ?)',
                     (phone, user_id))

def update_site_progress(phone: str, site_index: int, linked: bool = True):
    """Update site progress"""
    site_col = f'site{site_index}_linked'
    if USE_POSTGRES:
        execute_query(f'UPDATE number_progress SET {site_col} = %s, last_updated = CURRENT_TIMESTAMP WHERE phone_number = %s',
                     (1 if linked else 0, phone))
    else:
        execute_query(f'UPDATE number_progress SET {site_col} = ?, last_updated = CURRENT_TIMESTAMP WHERE phone_number = ?',
                     (1 if linked else 0, phone))

def check_and_complete_number(phone: str):
    """Check if all sites linked"""
    if USE_POSTGRES:
        row = execute_query('SELECT site1_linked, site2_linked, site3_linked, site4_linked FROM number_progress WHERE phone_number = %s',
                           (phone,), fetch='one')
    else:
        row = execute_query('SELECT site1_linked, site2_linked, site3_linked, site4_linked FROM number_progress WHERE phone_number = ?',
                           (phone,), fetch='one')
    
    if row and all(row):
        if USE_POSTGRES:
            execute_query('UPDATE number_progress SET completed = 1, last_updated = CURRENT_TIMESTAMP WHERE phone_number = %s', (phone,))
        else:
            execute_query('UPDATE number_progress SET completed = 1, last_updated = CURRENT_TIMESTAMP WHERE phone_number = ?', (phone,))
        return True
    return False

def get_incomplete_sites(phone: str) -> list:
    """Get incomplete sites"""
    progress = get_number_progress(phone)
    if not progress:
        return [1, 2, 3, 4]
    incomplete = []
    for i in range(1, 5):
        if not progress[f'site{i}_linked']:
            incomplete.append(i)
    return incomplete

def reset_daily_number_progress():
    """Reset incomplete progress"""
    if USE_POSTGRES:
        execute_query('DELETE FROM number_progress WHERE completed = 0')
    else:
        execute_query('DELETE FROM number_progress WHERE completed = 0')
    logger.info("Reset incomplete number progress")

