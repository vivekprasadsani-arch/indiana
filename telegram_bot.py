#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp OTP Telegram Bot
Multi-site OTP generation bot with admin approval system
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import base64
import sqlite3
import logging
import pytz
import requests
import schedule
import threading
import re
from datetime import datetime, time as dt_time
from typing import Optional, Dict, List

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== CONFIGURATION ====================

BOT_TOKEN = "8419074330:AAGGPd9rZEFPgbfzEadJtsWg4mouVLWKZns"
ADMIN_ID = 7325836764

# Site credentials
USERNAME = "9475595762"
PASSWORD = "raja0000"

# Sites configuration
SITES = {
    'coinzaapp': {'url': 'https://coinzaapp.com', 'name': 'Site 1', 'icon': '🔵'},
    'earnbro': {'url': 'https://earnbro.net', 'name': 'Site 2', 'icon': '🟢'},
    'kamate1': {'url': 'https://zapkaroapp.com', 'name': 'Site 3', 'icon': '🟡'},
    'kamkg': {'url': 'https://kamate1.com', 'name': 'Site 4', 'icon': '🔴'}
}

# Time configuration (Bangladesh timezone)
BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')
WORK_START_TIME = dt_time(10, 30)  # 10:30 AM
WORK_END_TIME = dt_time(15, 0)     # 3:00 PM
RESET_TIME = dt_time(8, 0)         # 8:00 AM
REPORT_TIME = dt_time(15, 0)       # 3:00 PM

# Payment per successful number
PAYMENT_PER_NUMBER = 10  # Taka

# Concurrent processing limits
MAX_CONCURRENT_PER_USER = 3  # Maximum numbers a user can process simultaneously
MAX_CONCURRENT_API_REQUESTS = 5  # Maximum concurrent OTP requests per site (API rate limit)

# Database
DB_PATH = "telegram_bot.db"

# ==================== LOGGING ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ACTIVE TASKS TRACKING ====================

# Track active processing tasks: {user_id: {phone: task}}
active_tasks = {}
tasks_lock = threading.Lock()  # Thread-safe lock for dictionary access

# ==================== API RATE LIMITING ====================

# Semaphores to limit concurrent API requests per site
site_semaphores = {}

def get_site_semaphore(site_key: str) -> asyncio.Semaphore:
    """Get or create semaphore for a site"""
    if site_key not in site_semaphores:
        site_semaphores[site_key] = asyncio.Semaphore(MAX_CONCURRENT_API_REQUESTS)
    return site_semaphores[site_key]

# ==================== DATABASE ====================

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Users table
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
    
    # Number progress tracking table
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
    
    # Daily stats table
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
    
    # Sessions table (for site logins)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            site_key TEXT PRIMARY KEY,
            token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Activity log
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
    conn.close()
    logger.info("Database initialized")

def get_user(user_id: int) -> Optional[Dict]:
    """Get user from database"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'last_name': row[3],
            'approved': row[4],
            'balance': row[5],
            'total_numbers': row[6],
            'daily_numbers': row[7],
            'joined_at': row[8]
        }
    return None

def add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
    """Add or update user in database"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, approved)
        VALUES (?, ?, ?, ?, COALESCE((SELECT approved FROM users WHERE user_id = ?), 0))
    ''', (user_id, username, first_name, last_name, user_id))
    
    conn.commit()
    conn.close()

def approve_user(user_id: int):
    """Approve user"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET approved = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def reject_user(user_id: int):
    """Reject user"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET approved = -1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def update_user_stats(user_id: int, numbers_added: int = 0, earnings: float = 0):
    """Update user statistics"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Update user totals
    cursor.execute('''
        UPDATE users 
        SET total_numbers = total_numbers + ?,
            daily_numbers = daily_numbers + ?,
            balance = balance + ?
        WHERE user_id = ?
    ''', (numbers_added, numbers_added, earnings, user_id))
    
    # Update daily stats
    today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
    cursor.execute('''
        INSERT INTO daily_stats (user_id, date, numbers_added, earnings)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            numbers_added = numbers_added + ?,
            earnings = earnings + ?
    ''', (user_id, today, numbers_added, earnings, numbers_added, earnings))
    
    conn.commit()
    conn.close()

def reset_daily_stats():
    """Reset daily statistics for all users"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET daily_numbers = 0')
    conn.commit()
    conn.close()
    
    # Also reset incomplete number progress
    reset_daily_number_progress()
    
    logger.info("Daily stats reset completed")

def get_daily_report() -> List[Dict]:
    """Get daily report for all users"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    today = datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.username, d.numbers_added, d.earnings
        FROM users u
        LEFT JOIN daily_stats d ON u.user_id = d.user_id AND d.date = ?
        WHERE u.approved = 1 AND (d.numbers_added > 0 OR d.numbers_added IS NULL)
        ORDER BY d.numbers_added DESC
    ''', (today,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            'user_id': row[0],
            'first_name': row[1],
            'username': row[2],
            'numbers_added': row[3] or 0,
            'earnings': row[4] or 0
        }
        for row in rows
    ]

def log_activity(user_id: int, action: str, details: str = ""):
    """Log user activity"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO activity_log (user_id, action, details)
        VALUES (?, ?, ?)
    ''', (user_id, action, details))
    conn.commit()
    conn.close()

# ==================== NUMBER PROGRESS TRACKING ====================

def get_number_progress(phone: str):
    """Get progress for a phone number"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM number_progress WHERE phone_number = ?', (phone,))
    row = cursor.fetchone()
    conn.close()
    
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
    """Initialize progress tracking for a new number"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Check if already exists
    cursor.execute('SELECT phone_number FROM number_progress WHERE phone_number = ?', (phone,))
    if cursor.fetchone():
        conn.close()
        return  # Already exists
    
    cursor.execute('''
        INSERT INTO number_progress (phone_number, user_id)
        VALUES (?, ?)
    ''', (phone, user_id))
    conn.commit()
    conn.close()

def update_site_progress(phone: str, site_index: int, linked: bool = True):
    """Update progress for a specific site (1-4)"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    site_column = f'site{site_index}_linked'
    cursor.execute(f'''
        UPDATE number_progress
        SET {site_column} = ?,
            last_updated = CURRENT_TIMESTAMP
        WHERE phone_number = ?
    ''', (1 if linked else 0, phone))
    conn.commit()
    conn.close()

def check_and_complete_number(phone: str):
    """Check if all 4 sites are linked and mark as completed"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT site1_linked, site2_linked, site3_linked, site4_linked
        FROM number_progress
        WHERE phone_number = ?
    ''', (phone,))
    
    row = cursor.fetchone()
    if row and all(row):
        # All 4 sites linked - mark as completed
        cursor.execute('''
            UPDATE number_progress
            SET completed = 1,
                last_updated = CURRENT_TIMESTAMP
            WHERE phone_number = ?
        ''', (phone,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM number_progress WHERE completed = 0')
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"Deleted {deleted_count} incomplete number progress records")

# ==================== WHATSAPP OTP SITE CLASS ====================

class WhatsAppOTPSite:
    """Handle WhatsApp OTP for a single site"""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        self.is_logged_in = False
    
    def _get_key_iv(self):
        """Get encryption key and IV from JWT token"""
        if not self.token:
            raise ValueError("No token")
        
        parts = self.token.split('.')
        payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
        decoded = base64.b64decode(payload)
        payload_data = json.loads(decoded)
        session_id = payload_data['sessionId'].replace('-', '')
        
        key = session_id[:16]
        iv = session_id[-16:]
        return key, iv
    
    def _encrypt(self, data):
        """Encrypt data using AES-CBC (hex encoded)"""
        key, iv = self._get_key_iv()
        
        if isinstance(data, dict):
            data = json.dumps(data, separators=(',', ':'))
        
        cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv.encode('utf-8'))
        padded = pad(data.encode('utf-8'), AES.block_size)
        encrypted = cipher.encrypt(padded)
        return encrypted.hex()
    
    def _decrypt(self, encrypted_hex):
        """Decrypt AES-CBC encrypted data (hex encoded)"""
        key, iv = self._get_key_iv()
        encrypted_bytes = bytes.fromhex(encrypted_hex)
        cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv.encode('utf-8'))
        decrypted = cipher.decrypt(encrypted_bytes)
        unpadded = unpad(decrypted, AES.block_size)
        return unpadded.decode('utf-8')
    
    def login(self):
        """Login and save session token"""
        try:
            password_hash = hashlib.md5(self.password.encode()).hexdigest()
            
            response = requests.post(
                f"{self.base_url}/pl3/access/login",
                json={
                    'reg_type': 1,
                    'phone': self.username,
                    'password': password_hash
                },
                headers=self.headers,
                timeout=15,
                verify=False
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0 and 'data' in result:
                    self.token = result['data'].get('token')
                    
                    if self.token:
                        self.headers['Authorization'] = f'Bearer {self.token}'
                        self.is_logged_in = True
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Login error for {self.base_url}: {e}")
            return False
    
    def get_otp(self, phone: str, retry: int = 3) -> Optional[str]:
        """Get OTP for phone number"""
        payload = {"phone_number": phone}
        
        for attempt in range(retry):
            try:
                encrypted_payload = self._encrypt(payload)
                
                response = requests.post(
                    f"{self.base_url}/pl3/2/ws/login_code/get",
                    json={'data': encrypted_payload},
                    headers=self.headers,
                    timeout=20,
                    verify=False
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if 'data' not in result:
                        if attempt < retry - 1:
                            # Reduced sleep from 2s to 0.5s
                            time.sleep(0.5)
                            continue
                        return None
                    
                    try:
                        decrypted = self._decrypt(result['data'])
                        response_data = json.loads(decrypted)
                        
                        if response_data.get('code') == 0 and 'data' in response_data:
                            return response_data['data'].get('login_code', '')
                        else:
                            if attempt < retry - 1:
                                # Reduced sleep from 3s to 0.5s
                                time.sleep(0.5)
                                continue
                            return None
                            
                    except Exception:
                        if attempt < retry - 1:
                            # Reduced sleep from 2s to 0.5s
                            time.sleep(0.5)
                            continue
                        return None
                        
                elif response.status_code in [401, 403]:
                    # Session expired - re-login
                    if self.login():
                        if attempt < retry - 1:
                            continue
                    return None
                else:
                    if attempt < retry - 1:
                        # Reduced sleep from 2s to 0.5s
                        time.sleep(0.5)
                        continue
                    return None
                    
            except requests.exceptions.Timeout:
                if attempt < retry - 1:
                    # Reduced sleep from 3s to 0.5s
                    time.sleep(0.5)
                    continue
                return None
            except Exception as e:
                logger.error(f"OTP error: {e}")
                if attempt < retry - 1:
                    # Reduced sleep from 2s to 0.5s
                    time.sleep(0.5)
                    continue
                return None
        
        return None
    
    def claim_reset_reward(self) -> dict:
        """Claim reset button reward (hourly reward)"""
        try:
            payload = {
                "activity_type": 2,
                "activity_id": 6
            }
            encrypted_payload = self._encrypt(payload)
            
            response = requests.post(
                f"{self.base_url}/pl3/activity/reset",
                json={'data': encrypted_payload},
                headers=self.headers,
                timeout=15,
                verify=False
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Decrypt response
                if 'data' in result and isinstance(result['data'], str):
                    try:
                        decrypted = self._decrypt(result['data'])
                        data = json.loads(decrypted)
                        
                        # code=0 means success, code=10000 means not ready yet
                        if data.get('code') == 0:
                            return {'success': True, 'msg': 'Reward claimed'}
                        elif data.get('code') == 10000:
                            return {'success': False, 'msg': 'Not ready yet'}
                        else:
                            return {'success': False, 'msg': data.get('msg', 'Unknown')}
                    except Exception as e:
                        return {'success': False, 'msg': f'Decrypt error: {e}'}
                
                return {'success': False, 'msg': 'Invalid response format'}
            else:
                return {'success': False, 'msg': f'HTTP {response.status_code}'}
        except Exception as e:
            return {'success': False, 'msg': str(e)}
    
    def check_status(self, phone: str) -> dict:
        """Check WhatsApp linking status - returns dict with status info"""
        try:
            payload = {"phone_number": phone}
            encrypted_payload = self._encrypt(payload)
            
            response = requests.post(
                f"{self.base_url}/pl3/2/ws/login/status",
                json={'data': encrypted_payload},
                headers=self.headers,
                timeout=10,
                verify=False
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Log full API response for debugging
                logger.info(f"📥 Full status API response for {phone}: {result}")
                
                # Check for simple status=1 success format
                if 'status' in result and result.get('status') == 1:
                    msg = result.get('msg', 'Success')
                    phone_clean = phone.replace('+', '').replace('-', '').replace(' ', '')
                    
                    # ONLY reject if there's explicit phone mismatch
                    if msg and 'number' in str(msg).lower():
                        numbers_in_msg = re.findall(r'\d{10,15}', str(msg))
                        if numbers_in_msg and numbers_in_msg[0] != phone_clean:
                            logger.warning(f"⚠️ Status=1 phone mismatch! Expected {phone_clean}, got {numbers_in_msg[0]}. Ignoring.")
                            return {
                                'success': False,
                                'waiting': True,
                                'code': 1,
                                'msg': msg
                            }
                    
                    # Accept all other status=1 responses
                    logger.info(f"✅ Status check (status=1): SUCCESS for {phone}")
                    return {
                        'success': True,
                        'waiting': False,
                        'code': 1,
                        'msg': msg
                    }
                
                # Check if code is at top level (new API format)
                if 'code' in result:
                    code = result.get('code')
                    msg = result.get('msg', '')
                    phone_clean = phone.replace('+', '').replace('-', '').replace(' ', '')
                    
                    # ONLY reject if there's explicit phone mismatch
                    if msg and 'number' in msg.lower():
                        numbers_in_msg = re.findall(r'\d{10,15}', msg)
                        if numbers_in_msg and numbers_in_msg[0] != phone_clean:
                            logger.warning(f"⚠️ PHONE MISMATCH! Expected {phone_clean}, got {numbers_in_msg[0]}. Ignoring.")
                            return {
                                'success': False,
                                'waiting': True,
                                'code': code,
                                'msg': f'Phone mismatch: {phone_clean} != {numbers_in_msg[0]}'
                            }
                    
                    # Multiple success codes possible
                    # 20003 = login success
                    # 20002 = has been bound (successfully linked!)
                    # 200, 0 = general success
                    # 1 = success (some APIs use this)
                    is_success = code in [20003, 20002, 200, 0, 1]
                    
                    # Check message for success indicators
                    if msg and ('success' in msg.lower() or 'login success' in msg.lower() or 'has been bound' in msg.lower()):
                        is_success = True
                    
                    logger.info(f"🔍 Status check (top-level): code={code}, msg={msg}, is_success={is_success}")
                    
                    return {
                        'success': is_success,
                        'waiting': code == 20001,  # 20001 = waiting
                        'code': code,
                        'msg': msg
                    }
                
                # Check if data is present (old API format)
                if 'data' in result:
                    data = result['data']
                    
                    # If data is already a dict, use it directly
                    if isinstance(data, dict) and data:  # Make sure it's not empty
                        code = data.get('code')
                        msg = data.get('msg', '')
                        phone_clean = phone.replace('+', '').replace('-', '').replace(' ', '')
                        
                        # ONLY reject if there's explicit phone mismatch
                        if msg and 'number' in msg.lower():
                            numbers_in_msg = re.findall(r'\d{10,15}', msg)
                            if numbers_in_msg and numbers_in_msg[0] != phone_clean:
                                logger.warning(f"⚠️ PHONE MISMATCH! Expected {phone_clean}, got {numbers_in_msg[0]}. Ignoring.")
                                return {
                                    'success': False,
                                    'waiting': True,
                                    'code': code,
                                    'msg': f'Phone mismatch: {phone_clean} != {numbers_in_msg[0]}'
                                }
                        
                        # Multiple success codes possible
                        is_success = code in [20003, 20002, 200, 0, 1]
                        if msg and ('success' in msg.lower() or 'login success' in msg.lower() or 'has been bound' in msg.lower()):
                            is_success = True
                        
                        logger.info(f"🔍 Status check (data dict): code={code}, msg={msg}, is_success={is_success}")
                        
                        return {
                            'success': is_success,
                            'waiting': code == 20001,
                            'code': code,
                            'msg': msg
                        }
                    
                    # If data is a string, decrypt it
                    elif isinstance(data, str):
                        try:
                            decrypted = self._decrypt(data)
                            status_data = json.loads(decrypted)
                            code = status_data.get('code')
                            msg = status_data.get('msg', '')
                            phone_clean = phone.replace('+', '').replace('-', '').replace(' ', '')
                            
                            # ONLY reject if there's explicit phone mismatch
                            if msg and 'number' in msg.lower():
                                numbers_in_msg = re.findall(r'\d{10,15}', msg)
                                if numbers_in_msg and numbers_in_msg[0] != phone_clean:
                                    logger.warning(f"⚠️ PHONE MISMATCH! Expected {phone_clean}, got {numbers_in_msg[0]}. Ignoring.")
                                    return {
                                        'success': False,
                                        'waiting': True,
                                        'code': code,
                                        'msg': f'Phone mismatch: {phone_clean} != {numbers_in_msg[0]}'
                                    }
                            
                            # Multiple success codes possible
                            is_success = code in [20003, 20002, 200, 0, 1]
                            if msg and ('success' in msg.lower() or 'login success' in msg.lower() or 'has been bound' in msg.lower()):
                                is_success = True
                            
                            logger.info(f"🔍 Status check (decrypted): code={code}, msg={msg}, is_success={is_success}")
                            
                            return {
                                'success': is_success,
                                'waiting': code == 20001,
                                'code': code,
                                'msg': msg
                            }
                        except Exception as e:
                            logger.error(f"❌ Decrypt error in check_status: {e}")
                            return {'success': False, 'waiting': True, 'code': None, 'msg': str(e)}
                
                logger.warning(f"Unexpected response format: {result}")
            else:
                logger.warning(f"Status check HTTP {response.status_code}")
            
            return {'success': False, 'waiting': True, 'code': None, 'msg': 'No response'}
        except Exception as e:
            logger.error(f"Status check error: {e}")
            return {'success': False, 'waiting': True, 'code': None, 'msg': str(e)}

# ==================== GLOBAL SESSION MANAGER ====================

class GlobalSessionManager:
    """Manage shared sessions for all users (thread-safe)"""
    
    def __init__(self):
        self.sites: Dict[str, WhatsAppOTPSite] = {}
        self._lock = threading.Lock()
        self._initialized = False
        self._last_login_time = {}
    
    def initialize_all(self) -> bool:
        """Login to all sites once at startup"""
        with self._lock:
            if self._initialized:
                return True
            
            success_count = 0
            
            for site_key, site_info in SITES.items():
                site = WhatsAppOTPSite(site_info['url'], USERNAME, PASSWORD)
                
                if site.login():
                    self.sites[site_key] = site
                    self._last_login_time[site_key] = time.time()
                    success_count += 1
                    logger.info(f"Global Session: Logged in to {site_info['name']}")
                else:
                    logger.error(f"Global Session: Failed to login to {site_info['name']}")
            
            if success_count == len(SITES):
                self._initialized = True
                return True
            return False
    
    def get_site(self, site_key: str) -> Optional[WhatsAppOTPSite]:
        """Get site session (thread-safe)"""
        with self._lock:
            return self.sites.get(site_key)
    
    def refresh_site(self, site_key: str) -> bool:
        """Re-login to a site if session expired"""
        with self._lock:
            site_info = SITES.get(site_key)
            if not site_info:
                return False
            
            logger.info(f"Global Session: Refreshing {site_info['name']}")
            site = WhatsAppOTPSite(site_info['url'], USERNAME, PASSWORD)
            
            if site.login():
                self.sites[site_key] = site
                self._last_login_time[site_key] = time.time()
                logger.info(f"Global Session: Refreshed {site_info['name']}")
                return True
            else:
                logger.error(f"Global Session: Failed to refresh {site_info['name']}")
                return False
    
    def is_initialized(self) -> bool:
        """Check if sessions are initialized"""
        return self._initialized
    
    def claim_all_reset_rewards(self) -> Dict[str, dict]:
        """Claim reset rewards from all sites"""
        results = {}
        
        with self._lock:
            for site_key, site in self.sites.items():
                site_info = SITES.get(site_key)
                try:
                    result = site.claim_reset_reward()
                    results[site_info['name']] = result
                    
                    if result['success']:
                        logger.info(f"Reset Reward: Claimed from {site_info['name']}")
                    else:
                        logger.info(f"Reset Reward: {site_info['name']} - {result['msg']}")
                except Exception as e:
                    logger.error(f"Reset Reward: Error claiming from {site_info['name']}: {e}")
                    results[site_info['name']] = {'success': False, 'msg': str(e)}
        
        return results


# Global session manager instance
global_session_manager = GlobalSessionManager()

# ==================== TIME CHECKS ====================

def is_working_hours() -> bool:
    """Check if current time is within working hours"""
    now = datetime.now(BANGLADESH_TZ).time()
    return WORK_START_TIME <= now <= WORK_END_TIME

def get_time_message() -> str:
    """Get message about working hours"""
    now = datetime.now(BANGLADESH_TZ)
    current_time = now.strftime('%I:%M %p')
    
    if is_working_hours():
        return f"✓ Service active (Current time: {current_time})"
    else:
        return f"⚠ Service offline\n\nWorking hours: 10:30 AM - 3:00 PM (Bangladesh Time)\nCurrent time: {current_time}"

# ==================== TELEGRAM HANDLERS ====================

def get_main_keyboard(is_admin: bool = False):
    """Get main reply keyboard"""
    if is_admin:
        keyboard = [
            ['💰 Balance', '📊 My Stats'],
            ['📈 Admin Panel', '❓ Help']
        ]
    else:
        keyboard = [
            ['💰 Balance', '📊 My Stats'],
            ['❓ Help']
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
    
    # Add or update user
    add_or_update_user(
        user_id,
        user.username or "",
        user.first_name or "",
        user.last_name or ""
    )
    
    # Auto-approve admin
    if user_id == ADMIN_ID:
        approve_user(user_id)
        logger.info(f"Admin {user_id} auto-approved")
    
    user_data = get_user(user_id)
    
    if user_data['approved'] == 0:
        # Pending approval - notify admin
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 <b>New User Request</b>\n\n"
                 f"User ID: <code>{user_id}</code>\n"
                 f"Name: {user.first_name or 'N/A'}\n"
                 f"Username: @{user.username or 'N/A'}\n\n"
                 f"To approve: /approve {user_id}\n"
                 f"To reject: /reject {user_id}",
            parse_mode=ParseMode.HTML
        )
        
        await update.message.reply_text(
            "👋 Welcome to WhatsApp OTP Bot!\n\n"
            "Your account is pending approval.\n"
            "You will be notified once approved.\n\n"
            "Please wait...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        log_activity(user_id, 'registration_request', f"Name: {user.first_name}")
        
    elif user_data['approved'] == -1:
        # Rejected
        await update.message.reply_text(
            "❌ Your account request was rejected.\n\n"
            "Please contact admin for more information.",
            reply_markup=ReplyKeyboardRemove()
        )
        
    else:
        # Approved
        time_status = get_time_message()
        
        await update.message.reply_text(
            f"👋 Welcome back, {user.first_name}!\n\n"
            f"💰 Balance: ৳{user_data['balance']:.2f}\n"
            f"📱 Total numbers: {user_data['total_numbers']}\n"
            f"📊 Today: {user_data['daily_numbers']} numbers\n\n"
            f"{time_status}\n\n"
            f"💵 Earnings: ৳{PAYMENT_PER_NUMBER} per number",
            reply_markup=get_main_keyboard(user_id == ADMIN_ID)
        )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve user (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /approve <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        approve_user(user_id)
        
        await update.message.reply_text(f"✅ User {user_id} approved!")
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Congratulations!\n\n"
                     "Your account has been approved.\n"
                     "You can now start adding numbers.\n\n"
                     "💵 Earnings: ৳10 per number\n"
                     "⏰ Working hours: 10:30 AM - 3:00 PM",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
        
        log_activity(user_id, 'approved', f"By admin {ADMIN_ID}")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject user (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /reject <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        reject_user(user_id)
        
        await update.message.reply_text(f"❌ User {user_id} rejected")
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Your account request was rejected.\n\n"
                     "Please contact admin for more information."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
        
        log_activity(user_id, 'rejected', f"By admin {ADMIN_ID}")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user balance"""
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if not user_data or user_data['approved'] != 1:
        await update.message.reply_text("❌ Access denied")
        return
    
    await update.message.reply_text(
        f"💰 <b>Your Balance</b>\n\n"
        f"Current: ৳{user_data['balance']:.2f}\n"
        f"Rate: ৳{PAYMENT_PER_NUMBER} per number\n\n"
        f"📊 Statistics:\n"
        f"• Total numbers: {user_data['total_numbers']}\n"
        f"• Today: {user_data['daily_numbers']} numbers\n"
        f"• Total earned: ৳{user_data['total_numbers'] * PAYMENT_PER_NUMBER:.2f}",
        parse_mode=ParseMode.HTML
    )

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if not user_data or user_data['approved'] != 1:
        await update.message.reply_text("❌ Access denied")
        return
    
    time_status = get_time_message()
    
    await update.message.reply_text(
        f"📊 <b>Your Statistics</b>\n\n"
        f"📱 Numbers Added:\n"
        f"• Today: {user_data['daily_numbers']}\n"
        f"• Total: {user_data['total_numbers']}\n\n"
        f"💰 Earnings:\n"
        f"• Balance: ৳{user_data['balance']:.2f}\n"
        f"• Rate: ৳{PAYMENT_PER_NUMBER}/number\n\n"
        f"📅 Member since: {user_data['joined_at'][:10]}\n\n"
        f"{time_status}",
        parse_mode=ParseMode.HTML
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await update.message.reply_text(
        "❓ <b>How to Use</b>\n\n"
        "1. Send phone number with country code\n"
        "   Example: <code>+12345678901</code>\n\n"
        "2. Receive 4 OTPs (one by one)\n\n"
        "3. Enter each OTP in WhatsApp:\n"
        "   • Open WhatsApp\n"
        "   • Go to Linked Devices\n"
        "   • Link with phone number\n"
        "   • Enter the OTP code\n\n"
        "4. Wait for confirmation before next OTP\n\n"
        "5. Earn ৳10 when all 4 sites linked!\n\n"
        "⏰ <b>Working Hours</b>\n"
        "10:30 AM - 3:00 PM (Bangladesh Time)\n\n"
        "💡 <b>Tips:</b>\n"
        "• Just send phone number, no button needed!\n"
        "• Use valid WhatsApp numbers\n"
        "• Complete one number before starting another\n"
        "• Numbers reset daily at 8:00 AM",
        parse_mode=ParseMode.HTML
    )

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel (admin only)"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only feature")
        return
    
    # Get all users stats
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE approved = 1')
    approved_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE approved = 0')
    pending_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(daily_numbers) FROM users WHERE approved = 1')
    today_total = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT SUM(total_numbers) FROM users WHERE approved = 1')
    all_time_total = cursor.fetchone()[0] or 0
    
    conn.close()
    
    await update.message.reply_text(
        f"📈 <b>Admin Panel</b>\n\n"
        f"👥 Users:\n"
        f"• Approved: {approved_count}\n"
        f"• Pending: {pending_count}\n\n"
        f"📊 Numbers:\n"
        f"• Today: {today_total}\n"
        f"• All time: {all_time_total}\n\n"
        f"💰 Payouts:\n"
        f"• Today: ৳{today_total * PAYMENT_PER_NUMBER:.2f}\n"
        f"• All time: ৳{all_time_total * PAYMENT_PER_NUMBER:.2f}\n\n"
        f"Commands:\n"
        f"/approve <user_id> - Approve user\n"
        f"/reject <user_id> - Reject user\n"
        f"/report - Daily report",
        parse_mode=ParseMode.HTML
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate daily report (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command")
        return
    
    report_data = get_daily_report()
    
    if not report_data:
        await update.message.reply_text("📊 No activity today")
        return
    
    report_text = f"📊 <b>Daily Report</b>\n"
    report_text += f"Date: {datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')}\n\n"
    
    total_numbers = 0
    total_earnings = 0
    
    for i, user in enumerate(report_data, 1):
        report_text += f"{i}. {user['first_name']}"
        if user['username']:
            report_text += f" (@{user['username']})"
        report_text += f"\n   Numbers: {user['numbers_added']}"
        report_text += f" | Earned: ৳{user['earnings']:.2f}\n\n"
        
        total_numbers += user['numbers_added']
        total_earnings += user['earnings']
    
    report_text += f"━━━━━━━━━━━━━━━━━\n"
    report_text += f"<b>Total:</b>\n"
    report_text += f"Numbers: {total_numbers}\n"
    report_text += f"Earnings: ৳{total_earnings:.2f}"
    
    await update.message.reply_text(report_text, parse_mode=ParseMode.HTML)

async def process_phone_number_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, phone: str):
    """Background task to process a single phone number with progress tracking"""
    
    loop = asyncio.get_event_loop()
    
    # Initialize or get existing progress
    await loop.run_in_executor(None, init_number_progress, phone, user_id)
    progress = await loop.run_in_executor(None, get_number_progress, phone)
    
    # Check if already completed
    if progress and progress['completed']:
        await update.message.reply_text(
            f"✅ {phone} already completed!\n\n"
            f"All 4 sites are already linked.\n"
            f"This number has been processed successfully.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get list of incomplete sites
    incomplete_sites = await loop.run_in_executor(None, get_incomplete_sites, phone)
    
    if not incomplete_sites:
        # All sites done, mark as completed
        await loop.run_in_executor(None, check_and_complete_number, phone)
        await update.message.reply_text(
            f"✅ {phone} completed!\n\n"
            f"All 4 sites already linked.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Show progress status
    total_sites = 4
    completed_count = total_sites - len(incomplete_sites)
    
    processing_msg = await update.message.reply_text(
        f"🔄 Processing {phone}...\n\n"
        f"Progress: {completed_count}/4 sites completed\n"
        f"Remaining: {len(incomplete_sites)} sites\n\n"
        f"Starting...",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Convert site list to indexed dict
        sites_list = list(SITES.items())
        
        # Process only incomplete sites
        for site_idx in incomplete_sites:
            site_key, site_info = sites_list[site_idx - 1]  # Convert 1-based to 0-based index
            site = global_session_manager.get_site(site_key)
            
            if not site:
                logger.error(f"[{phone}] Site {site_idx} ({site_info['name']}) not available")
                await update.message.reply_text(
                    f"❌ {site_info['icon']} Site {site_idx} unavailable\n\n"
                    f"⚠️ Process stopped. Please try again later.",
                    parse_mode=ParseMode.HTML
                )
                break
            
            # Update progress
            completed_count = total_sites - len(incomplete_sites) + (site_idx - incomplete_sites[0])
            await processing_msg.edit_text(
                f"🔄 Processing {phone}\n\n"
                f"Progress: {completed_count}/{total_sites}\n"
                f"{site_info['icon']} Site {site_idx}\n"
                f"⏳ Requesting OTP...",
                parse_mode=ParseMode.HTML
            )
            
            # Get OTP with rate limiting (max 5 concurrent per site)
            otp = None
            max_attempts = 3
            
            # Acquire semaphore to limit concurrent requests
            semaphore = get_site_semaphore(site_key)
            
            # Check if we need to wait in queue
            waiting_count = MAX_CONCURRENT_API_REQUESTS - semaphore._value
            if waiting_count >= MAX_CONCURRENT_API_REQUESTS:
                await update.message.reply_text(
                    f"⏳ Waiting in queue...\n\n"
                    f"Site {site_idx} is busy processing other requests.\n"
                    f"Your request will start soon.",
                    parse_mode=ParseMode.HTML
                )
            
            async with semaphore:
                logger.info(f"[{phone}] Acquired slot for site {site_idx} (available: {semaphore._value + 1}/{MAX_CONCURRENT_API_REQUESTS})")
                
                for attempt in range(1, max_attempts + 1):
                    logger.info(f"[{phone}] Attempting OTP request for site {site_idx}, attempt {attempt}/{max_attempts}")
                    
                    # Add small delay between users to avoid API hammering
                    if attempt == 1:
                        await asyncio.sleep(0.3)  # 300ms delay before first request
                    
                    otp = await loop.run_in_executor(None, site.get_otp, phone)
                    
                    if otp:
                        break
                    
                    if attempt < max_attempts:
                        logger.warning(f"[{phone}] OTP failed for {site_info['name']} attempt {attempt}, retrying...")
                        await asyncio.sleep(2)  # Wait 2 seconds before retry
                        
                        # Try refreshing session on 2nd attempt
                        if attempt == 2:
                            logger.info(f"[{phone}] Refreshing session for {site_info['name']}")
                            if await loop.run_in_executor(None, global_session_manager.refresh_site, site_key):
                                site = global_session_manager.get_site(site_key)
            
            logger.info(f"[{phone}] Released slot for site {site_idx}")
            
            if otp:
                otp_clean = otp.replace('-', '')
                
                # Send OTP to user (no site name!)
                await update.message.reply_text(
                    f"{site_info['icon']} <b>Site {site_idx}/{total_sites} - OTP Received</b>\n\n"
                    f"Code: <code>{otp_clean}</code>\n\n"
                    f"📲 Enter this in WhatsApp now:\n"
                    f"WhatsApp → Linked Devices → Link with phone number\n\n"
                    f"⏳ Waiting for confirmation...",
                    parse_mode=ParseMode.HTML
                )
                
                # Wait for confirmation (check every 1 second for instant detection!)
                confirmed = False
                last_code = None
                max_wait_time = 180  # 3 minutes for maximum reliability
                session_refreshed = False
                
                for check in range(max_wait_time):
                    try:
                        # Run check_status in thread pool to avoid blocking
                        status = await loop.run_in_executor(None, site.check_status, phone)
                        
                        # Enhanced logging for debugging
                        logger.debug(f"[{phone}] Check #{check}: status={status}")
                        
                        if status and status.get('success'):
                            confirmed = True
                            logger.info(f"✅ [{phone}] SUCCESS DETECTED at site {site_info['name']} after {check}s! Code={status.get('code')}")
                            break
                        
                        # Check for session expired (code=10002) and refresh (only once)
                        if status and status.get('code') == 10002 and not session_refreshed:
                            logger.warning(f"⚠️ [{phone}] Session expired during status check! Refreshing...")
                            session_refreshed = True  # Mark that we tried to refresh
                            
                            # Notify user
                            try:
                                await update.message.reply_text(
                                    f"⚠️ Session expired, refreshing...\n"
                                    f"Please wait a moment.",
                                    parse_mode=ParseMode.HTML
                                )
                            except:
                                pass
                            
                            refresh_success = await loop.run_in_executor(None, global_session_manager.refresh_site, site_key)
                            if refresh_success:
                                site = global_session_manager.get_site(site_key)
                                logger.info(f"✅ [{phone}] Session refreshed! Continuing status checks...")
                                # Reset last_code to force logging the next status
                                last_code = None
                                await asyncio.sleep(2)  # Wait a bit before next check
                                continue
                            else:
                                logger.error(f"❌ [{phone}] Failed to refresh session!")
                                # Continue checking anyway, maybe it will work
                        
                        # Log all status code changes for debugging
                        if status:
                            current_code = status.get('code')
                            if current_code != last_code and current_code is not None:
                                logger.info(f"📊 [{phone}] Status changed: code={current_code}, msg={status.get('msg', 'N/A')}, success={status.get('success')}, waiting={status.get('waiting')}")
                                last_code = current_code
                            elif check == 0:
                                # Log initial status
                                logger.info(f"🔍 [{phone}] Initial status: code={current_code}, msg={status.get('msg', 'N/A')}")
                        
                        # Update every 10 seconds
                        if check % 10 == 0 and check > 0:
                            try:
                                await processing_msg.edit_text(
                                    f"🔄 Processing {phone}\n\n"
                                    f"Progress: {completed_count}/{total_sites}\n"
                                    f"{site_info['icon']} Site {site_idx}\n"
                                    f"⏳ Waiting... ({check}s/{max_wait_time}s)\n"
                                    f"Status: {status.get('msg', 'Checking...') if status else 'Checking...'}",
                                    parse_mode=ParseMode.HTML
                                )
                            except:
                                pass  # Ignore edit errors
                    
                    except Exception as e:
                        logger.error(f"[{phone}] Status check error at site {site_info['name']}: {e}")
                        # Continue checking, maybe next attempt will work
                    
                    await asyncio.sleep(1)  # Check every 1 second (instant!)
                
                if confirmed:
                    # Save progress to database
                    await loop.run_in_executor(None, update_site_progress, phone, site_idx, True)
                    logger.info(f"[{phone}] Site {site_idx} ({site_info['name']}) successfully linked and saved")
                    
                    # Calculate new progress
                    current_completed = completed_count + 1
                    
                    await update.message.reply_text(
                        f"✅ {site_info['icon']} Site {site_idx} linked successfully!\n\n"
                        f"Progress: {current_completed}/{total_sites} completed\n"
                        f"{'Moving to next site...' if current_completed < total_sites else 'All sites done!'}",
                        parse_mode=ParseMode.HTML
                    )
                    # Immediately move to next site (no delay!)
                else:
                    # Timeout - stop processing and ask user to try again
                    logger.warning(f"[{phone}] Timeout at site {site_idx} ({site_info['name']}) after {max_wait_time}s")
                    
                    # Get current completed count
                    progress = await loop.run_in_executor(None, get_number_progress, phone)
                    current_completed = sum([
                        progress['site1_linked'],
                        progress['site2_linked'],
                        progress['site3_linked'],
                        progress['site4_linked']
                    ]) if progress else 0
                    
                    await update.message.reply_text(
                        f"⏰ {site_info['icon']} Site {site_idx} - Timeout after {max_wait_time}s\n\n"
                        f"❌ <b>Process stopped</b>\n\n"
                        f"Progress saved: {current_completed}/{total_sites} completed\n\n"
                        f"Please send the same number again to continue from where you left off.",
                        parse_mode=ParseMode.HTML
                    )
                    # Stop processing remaining sites
                    break
            else:
                # Failed to get OTP - stop processing
                logger.error(f"[{phone}] Failed to get OTP from site {site_idx} ({site_info['name']}) after {max_attempts} attempts")
                
                # Get current completed count
                progress = await loop.run_in_executor(None, get_number_progress, phone)
                current_completed = sum([
                    progress['site1_linked'],
                    progress['site2_linked'],
                    progress['site3_linked'],
                    progress['site4_linked']
                ]) if progress else 0
                
                await update.message.reply_text(
                    f"❌ {site_info['icon']} Site {site_idx} - Failed to get OTP\n\n"
                    f"❌ <b>Process stopped</b>\n\n"
                    f"Progress saved: {current_completed}/{total_sites} completed\n\n"
                    f"⚠️ Please try again in a few moments.\n"
                    f"Send the same number to continue.",
                    parse_mode=ParseMode.HTML
                )
                # Stop processing remaining sites
                break
        
        # Check if all 4 sites are now completed
        is_completed = await loop.run_in_executor(None, check_and_complete_number, phone)
        
        if is_completed:
            # All 4 sites successful - add earnings and mark as complete
            await loop.run_in_executor(None, update_user_stats, user_id, 1, PAYMENT_PER_NUMBER)
            user_data = await loop.run_in_executor(None, get_user, user_id)
            
            await processing_msg.edit_text(
                f"🎉 <b>SUCCESS!</b>\n\n"
                f"Number: {phone}\n"
                f"✅ All 4 sites linked!\n\n"
                f"💰 Earned: ৳{PAYMENT_PER_NUMBER:.2f}\n"
                f"💰 New balance: ৳{user_data['balance']:.2f}\n\n"
                f"📊 Today: {user_data['daily_numbers']} numbers added\n"
                f"📊 Total: {user_data['total_numbers']} numbers",
                parse_mode=ParseMode.HTML
            )
            
            await loop.run_in_executor(None, log_activity, user_id, 'number_added', f"Phone: {phone}, Earnings: {PAYMENT_PER_NUMBER}")
        else:
            # Get current progress
            progress = await loop.run_in_executor(None, get_number_progress, phone)
            if progress:
                completed_sites = sum([
                    progress['site1_linked'],
                    progress['site2_linked'],
                    progress['site3_linked'],
                    progress['site4_linked']
                ])
                
                await processing_msg.edit_text(
                    f"⏸️ <b>Progress Saved</b>\n\n"
                    f"Number: {phone}\n"
                    f"✅ Completed: {completed_sites}/4 sites\n"
                    f"⏳ Remaining: {4 - completed_sites} sites\n\n"
                    f"💡 Send the same number again to continue!",
                    parse_mode=ParseMode.HTML
                )
    
    except Exception as e:
        logger.error(f"[{phone}] Error processing: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ Error processing {phone}\n\n"
                f"Please try again later.",
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    finally:
        # Remove from active tasks
        with tasks_lock:
            if user_id in active_tasks and phone in active_tasks[user_id]:
                del active_tasks[user_id][phone]
                if not active_tasks[user_id]:
                    del active_tasks[user_id]
        
        logger.info(f"[{phone}] Task completed for user {user_id}")


async def process_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number from user and start background processing"""
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    
    # Check if user is approved
    loop = asyncio.get_event_loop()
    user_data = await loop.run_in_executor(None, get_user, user_id)
    if not user_data or user_data['approved'] != 1:
        await update.message.reply_text(
            "❌ Access denied\n\n"
            "Your account is pending approval.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check working hours
    if not is_working_hours():
        time_msg = get_time_message()
        await update.message.reply_text(
            f"⏰ Service is currently offline\n\n{time_msg}",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Validate phone format
    if not phone.startswith('+') or len(phone) < 10:
        await update.message.reply_text(
            "❌ Invalid phone number format!\n\n"
            "Please send with country code:\n"
            "Example: <code>+12345678901</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if global sessions are initialized
    if not global_session_manager.is_initialized():
        await update.message.reply_text(
            "⚠️ <b>Bot Initializing</b>\n\n"
            "Please wait a moment and try again.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user already has a task running for this phone number
    with tasks_lock:
        if user_id in active_tasks:
            # Check if already processing this specific number
            if phone in active_tasks[user_id]:
                already_processing = True
                too_many_tasks = False
            # Check if user has too many concurrent tasks
            elif len(active_tasks[user_id]) >= MAX_CONCURRENT_PER_USER:
                already_processing = False
                too_many_tasks = True
            else:
                already_processing = False
                too_many_tasks = False
        else:
            already_processing = False
            too_many_tasks = False
        
        if not already_processing and not too_many_tasks:
            # Register this task placeholder
            if user_id not in active_tasks:
                active_tasks[user_id] = {}
            active_tasks[user_id][phone] = True  # Placeholder, will be replaced with task
    
    if already_processing:
        await update.message.reply_text(
            f"⚠️ Already processing {phone}\n\n"
            f"Please wait for the current process to complete.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if too_many_tasks:
        await update.message.reply_text(
            f"⚠️ Too many concurrent numbers!\n\n"
            f"You are currently processing {len(active_tasks[user_id])} numbers.\n"
            f"Please wait for at least one to complete.\n\n"
            f"Maximum: {MAX_CONCURRENT_PER_USER} at a time",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Create background task for this phone number
    task = asyncio.create_task(
        process_phone_number_task(update, context, user_id, phone)
    )
    
    # Update with actual task
    with tasks_lock:
        active_tasks[user_id][phone] = task
    
    logger.info(f"Started background task for user {user_id}, phone {phone}")

# ==================== SCHEDULED TASKS ====================

def daily_reset_task():
    """Daily reset at 8:00 AM"""
    logger.info("Running daily reset...")
    reset_daily_stats()

async def send_daily_report_async(application):
    """Async helper to send daily report"""
    report_data = get_daily_report()
    
    if not report_data:
        logger.info("No report data - skipping daily report")
        return
    
    report_text = f"📊 <b>Daily Report</b>\n"
    report_text += f"Date: {datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d')}\n\n"
    
    total_numbers = 0
    total_earnings = 0
    
    for i, user in enumerate(report_data, 1):
        report_text += f"{i}. {user['first_name']}"
        if user['username']:
            report_text += f" (@{user['username']})"
        report_text += f"\n   Numbers: {user['numbers_added']}"
        report_text += f" | Earned: ৳{user['earnings']:.2f}\n\n"
        
        total_numbers += user['numbers_added']
        total_earnings += user['earnings']
    
    report_text += f"━━━━━━━━━━━━━━━━━\n"
    report_text += f"<b>Total:</b>\n"
    report_text += f"Numbers: {total_numbers}\n"
    report_text += f"Earnings: ৳{total_earnings:.2f}"
    
    # Send to admin
    try:
        await application.bot.send_message(
            chat_id=ADMIN_ID,
            text=report_text,
            parse_mode=ParseMode.HTML
        )
        logger.info("Daily report sent to admin successfully")
    except Exception as e:
        logger.error(f"Failed to send daily report: {e}")

async def claim_hourly_rewards_async(application):
    """Claim hourly reset rewards from all sites"""
    try:
        results = global_session_manager.claim_all_reset_rewards()
        
        # Count successes
        success_count = sum(1 for r in results.values() if r['success'])
        
        # Prepare notification message
        from datetime import datetime
        bd_time = datetime.now(BANGLADESH_TZ)
        time_str = bd_time.strftime("%I:%M %p, %d %b %Y")
        
        message = f"⏰ <b>Hourly Reward Claim Report</b>\n"
        message += f"🕐 Time: {time_str}\n\n"
        
        # Show results for each site
        for site_name, result in results.items():
            site_config = SITES.get(site_name, {})
            site_icon = site_config.get('icon', '🔘')
            site_display = site_config.get('name', site_name)
            
            if result['success']:
                message += f"{site_icon} <b>{site_display}</b>: ✅ Claimed\n"
                if result.get('message'):
                    message += f"   └─ {result['message']}\n"
            else:
                message += f"{site_icon} <b>{site_display}</b>: ⏳ Not Ready\n"
                if result.get('message'):
                    message += f"   └─ {result['message']}\n"
        
        message += f"\n📊 <b>Summary:</b> {success_count}/{len(results)} rewards claimed"
        
        # Log the result
        if success_count > 0:
            logger.info(f"Hourly Claim: {success_count}/{len(results)} rewards claimed successfully")
        else:
            logger.info(f"Hourly Claim: No rewards ready yet")
        
        # Send notification to admin
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text=message,
                parse_mode=ParseMode.HTML
            )
            logger.info("Hourly claim notification sent to admin")
        except Exception as notify_error:
            logger.error(f"Failed to send hourly claim notification: {notify_error}")
            
    except Exception as e:
        logger.error(f"Hourly claim error: {e}")
        
        # Send error notification to admin
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ <b>Hourly Claim Error</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

def hourly_claim_task(application, loop):
    """Hourly reset reward claim - called from scheduler thread"""
    logger.info("Checking hourly reset rewards...")
    
    # Schedule in bot's event loop from scheduler thread
    try:
        asyncio.run_coroutine_threadsafe(claim_hourly_rewards_async(application), loop)
        logger.info("Hourly claim task scheduled")
    except Exception as e:
        logger.error(f"Failed to schedule hourly claim: {e}")

def daily_report_task(application, loop):
    """Daily report at 3:00 PM - called from scheduler thread"""
    logger.info("Generating daily report...")
    
    # Schedule in bot's event loop from scheduler thread
    try:
        asyncio.run_coroutine_threadsafe(send_daily_report_async(application), loop)
        logger.info("Daily report task scheduled")
    except Exception as e:
        logger.error(f"Failed to schedule daily report: {e}")

def schedule_tasks(application, event_loop):
    """Schedule daily tasks and hourly claims with Bangladesh timezone awareness"""
    
    def run_schedule():
        """Scheduler loop with timezone-aware checks"""
        last_report_date = None
        last_reset_date = None
        last_hourly_check = None
        
        while True:
            try:
                bd_now = datetime.now(BANGLADESH_TZ)
                current_time = bd_now.time()
                current_date = bd_now.date()
                current_hour = bd_now.hour
                current_minute = bd_now.minute
                
                # Daily reset at 8:00 AM
                if current_time >= RESET_TIME and last_reset_date != current_date:
                    if current_time < dt_time(8, 5):  # 5 minute window
                        logger.info("Running daily reset task...")
                        daily_reset_task()
                        last_reset_date = current_date
                
                # Daily report at 3:00 PM
                if current_time >= REPORT_TIME and last_report_date != current_date:
                    if current_time < dt_time(15, 5):  # 5 minute window
                        logger.info("Running daily report task...")
                        daily_report_task(application, event_loop)
                        last_report_date = current_date
                
                # Hourly claim at :30 minute mark
                hour_minute_key = f"{current_hour}:{current_minute}"
                if current_minute == 30 and last_hourly_check != hour_minute_key:
                    logger.info(f"Running hourly claim task at {bd_now.strftime('%I:%M %p')}...")
                    hourly_claim_task(application, event_loop)
                    last_hourly_check = hour_minute_key
                
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            time.sleep(60)  # Check every minute
    
    scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
    scheduler_thread.start()
    
    # Log current time
    bd_now = datetime.now(BANGLADESH_TZ)
    logger.info(f"Scheduler started - Current BD time: {bd_now.strftime('%I:%M %p, %B %d, %Y')}")
    logger.info(f"Daily report: 3:00 PM BD Time | Daily reset: 8:00 AM BD Time")
    logger.info(f"Hourly rewards: Every hour at :30 minute mark (24 times/day)")

# ==================== MAIN ====================

async def post_init(application):
    """Post initialization - called after bot starts"""
    # Get the running event loop and start scheduler
    loop = asyncio.get_running_loop()
    schedule_tasks(application, loop)

def main():
    """Start the bot"""
    print("\n" + "="*60)
    print("  WhatsApp OTP Telegram Bot")
    print("  Global Shared Sessions for All Users")
    print("="*60 + "\n")
    
    # Initialize database
    init_db()
    print("[OK] Database initialized")
    
    # Initialize global sessions at startup
    print("\n[*] Logging in to all sites...")
    if global_session_manager.initialize_all():
        print("[OK] All sites logged in successfully")
        print("[OK] Sessions ready for all users")
        print("[OK] 100+ users can work simultaneously\n")
    else:
        print("[!] Some sites failed to login")
        print("Bot will continue, sessions will retry on demand\n")
    
    # Create application with larger thread pool for 100+ concurrent users
    from concurrent.futures import ThreadPoolExecutor
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)  # Enable concurrent update processing
        .post_init(post_init)  # Initialize scheduler after bot starts
        .build()
    )
    
    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(CommandHandler("report", report_command))
    
    # Phone number handler (any message starting with +)
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'^\+\d{10,15}$') & ~filters.COMMAND,
            process_phone_number
        )
    )
    
    # Menu handlers
    application.add_handler(MessageHandler(filters.Regex('^💰 Balance$'), balance_handler))
    application.add_handler(MessageHandler(filters.Regex('^📊 My Stats$'), stats_handler))
    application.add_handler(MessageHandler(filters.Regex('^❓ Help$'), help_handler))
    application.add_handler(MessageHandler(filters.Regex('^📈 Admin Panel$'), admin_panel_handler))
    
    # Start bot
    print("[OK] Bot started successfully!")
    print("\n" + "="*60)
    print("  Bot is running...")
    print("  Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

