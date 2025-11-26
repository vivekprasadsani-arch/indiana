#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp OTP Telegram Bot - Production Deployment Version
Uses PostgreSQL (Supabase) for production
"""

import os

# Check if DATABASE_URL is set for production
if not os.getenv("DATABASE_URL"):
    print("ERROR: DATABASE_URL environment variable not set!")
    print("This is the production version. For local development, use telegram_bot.py")
    exit(1)

# Import PostgreSQL database module
import database_postgres as db

# Import rest of bot functionality from original file
# We'll use exec to load and modify the original bot code

import sys
import logging

logger = logging.getLogger(__name__)

# Read the original bot file
with open('telegram_bot.py', 'r', encoding='utf-8') as f:
    bot_code = f.read()

# Replace database function calls to use our PostgreSQL module
replacements = {
    'def init_db():': 'def init_db():\n    """Initialize PostgreSQL database"""\n    return db.init_db_pool(DATABASE_URL)',
    'def get_user(': 'def get_user_REPLACED(',
    'def add_or_update_user(': 'def add_or_update_user_REPLACED(',
    'def approve_user(': 'def approve_user_REPLACED(',
    'def reject_user(': 'def reject_user_REPLACED(',
    'def update_user_stats(': 'def update_user_stats_REPLACED(',
    'def reset_daily_stats(': 'def reset_daily_stats_REPLACED(',
    'def get_daily_report(': 'def get_daily_report_REPLACED(',
    'def log_activity(': 'def log_activity_REPLACED(',
    'def get_number_progress(': 'def get_number_progress_REPLACED(',
    'def init_number_progress(': 'def init_number_progress_REPLACED(',
    'def update_site_progress(': 'def update_site_progress_REPLACED(',
    'def check_and_complete_number(': 'def check_and_complete_number_REPLACED(',
    'def get_incomplete_sites(': 'def get_incomplete_sites_REPLACED(',
    'def reset_daily_number_progress(': 'def reset_daily_number_progress_REPLACED(',
}

# This is getting complex. Let me use a simpler approach - direct module imports

# Actually let's just patch the functions directly
from telegram_bot import *

# Override database functions with PostgreSQL versions
get_user = db.get_user
add_or_update_user = db.add_or_update_user
approve_user = db.approve_user
reject_user = db.reject_user
update_user_stats = db.update_user_stats
reset_daily_stats = db.reset_daily_stats
get_daily_report = db.get_daily_report
log_activity = db.log_activity
get_number_progress = db.get_number_progress
init_number_progress = db.init_number_progress
update_site_progress = db.update_site_progress
check_and_complete_number = db.check_and_complete_number
get_incomplete_sites = db.get_incomplete_sites
reset_daily_number_progress = db.reset_daily_number_progress

# Override init_db
def init_db():
    """Initialize PostgreSQL database"""
    print("[*] Connecting to PostgreSQL (Supabase)...")
    if db.init_db_pool(DATABASE_URL):
        print("[OK] PostgreSQL connected")
        return True
    else:
        print("[ERROR] Failed to connect to PostgreSQL")
        return False

# Now run the bot
if __name__ == '__main__':
    # Inject our PostgreSQL functions into telegram_bot module
    import telegram_bot as bot_module
    bot_module.init_db = init_db
    bot_module.get_user = db.get_user
    bot_module.add_or_update_user = db.add_or_update_user
    bot_module.approve_user = db.approve_user
    bot_module.reject_user = db.reject_user
    bot_module.update_user_stats = db.update_user_stats
    bot_module.reset_daily_stats = db.reset_daily_stats
    bot_module.get_daily_report = db.get_daily_report
    bot_module.log_activity = db.log_activity
    bot_module.get_number_progress = db.get_number_progress
    bot_module.init_number_progress = db.init_number_progress
    bot_module.update_site_progress = db.update_site_progress
    bot_module.check_and_complete_number = db.check_and_complete_number
    bot_module.get_incomplete_sites = db.get_incomplete_sites
    bot_module.reset_daily_number_progress = db.reset_daily_number_progress
    bot_module.reset_daily_stats = lambda: (db.reset_daily_stats(), db.reset_daily_number_progress())
    
    # Start the bot
    bot_module.main()

