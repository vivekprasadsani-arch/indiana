-- ==========================================
-- WhatsApp OTP Telegram Bot - Supabase Setup
-- ==========================================
-- Run this SQL in Supabase SQL Editor
-- ==========================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    approved INTEGER DEFAULT 0,
    balance NUMERIC(10, 2) DEFAULT 0,
    total_numbers INTEGER DEFAULT 0,
    daily_numbers INTEGER DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_users_approved ON users(approved);

-- Number progress tracking table
CREATE TABLE IF NOT EXISTS number_progress (
    phone_number TEXT PRIMARY KEY,
    user_id BIGINT,
    site1_linked INTEGER DEFAULT 0,
    site2_linked INTEGER DEFAULT 0,
    site3_linked INTEGER DEFAULT 0,
    site4_linked INTEGER DEFAULT 0,
    completed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_number_progress_user ON number_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_number_progress_completed ON number_progress(completed);

-- Daily stats table
CREATE TABLE IF NOT EXISTS daily_stats (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    date TEXT,
    numbers_added INTEGER DEFAULT 0,
    earnings NUMERIC(10, 2) DEFAULT 0,
    UNIQUE(user_id, date)
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_daily_stats_user_date ON daily_stats(user_id, date);

-- Sessions table (for site logins)
CREATE TABLE IF NOT EXISTS sessions (
    site_key TEXT PRIMARY KEY,
    token TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Activity log
CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    action TEXT,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_activity_log_user ON activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp ON activity_log(timestamp);

-- Success message
SELECT 'Database setup completed successfully!' AS status;

