#!/usr/bin/env python3
"""
Simple production runner - patches database functions for PostgreSQL
Original telegram_bot.py remains 100% unchanged
"""
import os
import sys

# For production, use PostgreSQL
if os.getenv("DATABASE_URL"):
    print("[PRODUCTION] Using PostgreSQL")
    
    # Import PostgreSQL
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import pytz
    from datetime import datetime
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')
    
    # Create connection pool
    from psycopg2 import pool
    db_pool = pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
    
    def get_conn():
        return db_pool.getconn()
    
    def put_conn(conn):
        db_pool.putconn(conn)
    
    # PostgreSQL versions of database functions
    def pg_exec(query, params=(), fetch=None):
        """Execute PostgreSQL query"""
        conn = get_conn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor if fetch == 'dict' else None)
            cursor.execute(query.replace('?', '%s'), params)
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
            print(f"DB Error: {e}")
            return None if fetch else False
        finally:
            put_conn(conn)
    
    # Import telegram_bot
    import telegram_bot as bot
    
    # Patch init_db
    original_init_db = bot.init_db
    def patched_init_db():
        print("[OK] Using PostgreSQL (tables should already exist in Supabase)")
        return True
    bot.init_db = patched_init_db
    
    # Patch database functions
    original_get_user = bot.get_user
    def patched_get_user(user_id):
        return pg_exec('SELECT * FROM users WHERE user_id = %s', (user_id,), fetch='dict')
    bot.get_user = patched_get_user
    
    original_add_or_update_user = bot.add_or_update_user
    def patched_add_or_update_user(user_id, username, first_name, last_name):
        pg_exec('''
            INSERT INTO users (user_id, username, first_name, last_name, approved)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = %s, first_name = %s, last_name = %s
        ''', (user_id, username, first_name, last_name, username, first_name, last_name))
    bot.add_or_update_user = patched_add_or_update_user
    
    original_approve_user = bot.approve_user
    def patched_approve_user(user_id):
        pg_exec('UPDATE users SET approved = 1 WHERE user_id = %s', (user_id,))
    bot.approve_user = patched_approve_user
    
    original_reject_user = bot.reject_user
    def patched_reject_user(user_id):
        pg_exec('UPDATE users SET approved = -1 WHERE user_id = %s', (user_id,))
    bot.reject_user = patched_reject_user
    
    original_update_user_stats = bot.update_user_stats  
    def patched_update_user_stats(user_id, numbers_added=0, earnings=0):
        pg_exec('''
            UPDATE users 
            SET total_numbers = total_numbers + %s,
                daily_numbers = daily_numbers + %s,
                balance = balance + %s
            WHERE user_id = %s
        ''', (numbers_added, numbers_added, earnings, user_id))
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        pg_exec('''
            INSERT INTO daily_stats (user_id, date, numbers_added, earnings)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                numbers_added = daily_stats.numbers_added + %s,
                earnings = daily_stats.earnings + %s
        ''', (user_id, today, numbers_added, earnings, numbers_added, earnings))
    bot.update_user_stats = patched_update_user_stats
    
    original_reset_daily_stats = bot.reset_daily_stats
    def patched_reset_daily_stats():
        pg_exec('UPDATE users SET daily_numbers = 0')
        pg_exec('DELETE FROM number_progress WHERE completed = 0')
    bot.reset_daily_stats = patched_reset_daily_stats
    
    original_get_daily_report = bot.get_daily_report
    def patched_get_daily_report():
        today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
        conn = get_conn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
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
            return [dict(r) for r in rows]
        finally:
            put_conn(conn)
    bot.get_daily_report = patched_get_daily_report
    
    original_log_activity = bot.log_activity
    def patched_log_activity(user_id, action, details=""):
        pg_exec('INSERT INTO activity_log (user_id, action, details) VALUES (%s, %s, %s)',
                (user_id, action, details))
    bot.log_activity = patched_log_activity
    
    original_get_number_progress = bot.get_number_progress
    def patched_get_number_progress(phone):
        row = pg_exec('SELECT * FROM number_progress WHERE phone_number = %s', (phone,), fetch='dict')
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
    bot.get_number_progress = patched_get_number_progress
    
    original_init_number_progress = bot.init_number_progress
    def patched_init_number_progress(phone, user_id):
        pg_exec('INSERT INTO number_progress (phone_number, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (phone, user_id))
    bot.init_number_progress = patched_init_number_progress
    
    original_update_site_progress = bot.update_site_progress
    def patched_update_site_progress(phone, site_index, linked=True):
        site_col = f'site{site_index}_linked'
        query = f'UPDATE number_progress SET {site_col} = %s, last_updated = CURRENT_TIMESTAMP WHERE phone_number = %s'
        pg_exec(query, (1 if linked else 0, phone))
    bot.update_site_progress = patched_update_site_progress
    
    original_check_and_complete_number = bot.check_and_complete_number
    def patched_check_and_complete_number(phone):
        row = pg_exec('SELECT site1_linked, site2_linked, site3_linked, site4_linked FROM number_progress WHERE phone_number = %s',
                      (phone,), fetch='one')
        if row and all(row):
            pg_exec('UPDATE number_progress SET completed = 1, last_updated = CURRENT_TIMESTAMP WHERE phone_number = %s',
                    (phone,))
            return True
        return False
    bot.check_and_complete_number = patched_check_and_complete_number
    
    original_get_incomplete_sites = bot.get_incomplete_sites
    def patched_get_incomplete_sites(phone):
        progress = patched_get_number_progress(phone)
        if not progress:
            return [1, 2, 3, 4]
        incomplete = []
        for i in range(1, 5):
            if not progress[f'site{i}_linked']:
                incomplete.append(i)
        return incomplete
    bot.get_incomplete_sites = patched_get_incomplete_sites
    
    original_reset_daily_number_progress = bot.reset_daily_number_progress
    def patched_reset_daily_number_progress():
        pg_exec('DELETE FROM number_progress WHERE completed = 0')
    bot.reset_daily_number_progress = patched_reset_daily_number_progress
    
    print("[OK] All database functions patched for PostgreSQL")
    print("[OK] Starting bot...")
    
    # Run bot
    bot.main()
else:
    # Local development - use original SQLite bot
    print("[LOCAL] Using SQLite")
    import telegram_bot
    telegram_bot.main()

