#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL Database Functions for Telegram Bot
Replaces SQLite with PostgreSQL for production deployment
"""

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from typing import Optional, Dict, List
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

# Bangladesh timezone
BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')

# Global connection pool
db_pool = None

def init_db_pool(database_url: str):
    """Initialize PostgreSQL connection pool"""
    global db_pool
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=database_url
        )
        logger.info("PostgreSQL connection pool initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        return False

def get_db_connection():
    """Get a connection from the pool"""
    if db_pool:
        return db_pool.getconn()
    return None

def return_db_connection(conn):
    """Return connection to the pool"""
    if db_pool and conn:
        db_pool.putconn(conn)

# ==================== USER FUNCTIONS ====================

def get_user(user_id: int) -> Optional[Dict]:
    """Get user from database"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None
    finally:
        return_db_connection(conn)

def add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
    """Add or update user in database"""
    conn = get_db_connection()
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
        logger.error(f"Error adding/updating user: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def approve_user(user_id: int):
    """Approve user"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET approved = 1 WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
    except Exception as e:
        logger.error(f"Error approving user: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def reject_user(user_id: int):
    """Reject user"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET approved = -1 WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
    except Exception as e:
        logger.error(f"Error rejecting user: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def update_user_stats(user_id: int, numbers_added: int = 0, earnings: float = 0):
    """Update user statistics"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # Update user totals
        cursor.execute('''
            UPDATE users 
            SET total_numbers = total_numbers + %s,
                daily_numbers = daily_numbers + %s,
                balance = balance + %s
            WHERE user_id = %s
        ''', (numbers_added, numbers_added, earnings, user_id))
        
        # Update daily stats
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
        logger.error(f"Error updating user stats: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def reset_daily_stats():
    """Reset daily statistics for all users"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET daily_numbers = 0')
        conn.commit()
        cursor.close()
        
        # Also reset incomplete number progress
        reset_daily_number_progress()
        
        logger.info("Daily stats reset completed")
    except Exception as e:
        logger.error(f"Error resetting daily stats: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def get_daily_report() -> List[Dict]:
    """Get daily report for all users"""
    conn = get_db_connection()
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
        logger.error(f"Error getting daily report: {e}")
        return []
    finally:
        return_db_connection(conn)

def log_activity(user_id: int, action: str, details: str = ""):
    """Log user activity"""
    conn = get_db_connection()
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
        logger.error(f"Error logging activity: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

# ==================== NUMBER PROGRESS FUNCTIONS ====================

def get_number_progress(phone: str):
    """Get progress for a phone number"""
    conn = get_db_connection()
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
        logger.error(f"Error getting number progress: {e}")
        return None
    finally:
        return_db_connection(conn)

def init_number_progress(phone: str, user_id: int):
    """Initialize progress tracking for a new number"""
    conn = get_db_connection()
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
        logger.error(f"Error initializing number progress: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def update_site_progress(phone: str, site_index: int, linked: bool = True):
    """Update progress for a specific site (1-4)"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        site_column = f'site{site_index}_linked'
        query = f'''
            UPDATE number_progress
            SET {site_column} = %s,
                last_updated = CURRENT_TIMESTAMP
            WHERE phone_number = %s
        '''
        cursor.execute(query, (1 if linked else 0, phone))
        conn.commit()
        cursor.close()
    except Exception as e:
        logger.error(f"Error updating site progress: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

def check_and_complete_number(phone: str):
    """Check if all 4 sites are linked and mark as completed"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT site1_linked, site2_linked, site3_linked, site4_linked
            FROM number_progress
            WHERE phone_number = %s
        ''', (phone,))
        
        row = cursor.fetchone()
        if row and all(row):
            # All 4 sites linked - mark as completed
            cursor.execute('''
                UPDATE number_progress
                SET completed = 1,
                    last_updated = CURRENT_TIMESTAMP
                WHERE phone_number = %s
            ''', (phone,))
            conn.commit()
            cursor.close()
            return True
        cursor.close()
        return False
    except Exception as e:
        logger.error(f"Error checking completion: {e}")
        conn.rollback()
        return False
    finally:
        return_db_connection(conn)

def get_incomplete_sites(phone: str) -> list:
    """Get list of site indices (1-4) that are not yet linked"""
    progress = get_number_progress(phone)
    if not progress:
        return [1, 2, 3, 4]  # All sites need to be done
    
    incomplete = []
    for i in range(1, 5):
        if not progress[f'site{i}_linked']:
            incomplete.append(i)
    
    return incomplete

def reset_daily_number_progress():
    """Reset all incomplete number progress daily"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM number_progress WHERE completed = 0')
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        logger.info(f"Deleted {deleted_count} incomplete number progress records")
    except Exception as e:
        logger.error(f"Error resetting number progress: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)

# ==================== ADMIN FUNCTIONS ====================

def get_admin_stats():
    """Get admin panel statistics"""
    conn = get_db_connection()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        stats = {}
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE approved = 1')
        stats['approved_count'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE approved = 0')
        stats['pending_count'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COALESCE(SUM(daily_numbers), 0) FROM users WHERE approved = 1')
        stats['today_total'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COALESCE(SUM(total_numbers), 0) FROM users WHERE approved = 1')
        stats['all_time_total'] = cursor.fetchone()[0]
        
        cursor.close()
        return stats
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        return {}
    finally:
        return_db_connection(conn)

