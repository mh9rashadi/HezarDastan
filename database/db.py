import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "database/users.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """ایجاد جداول مورد نیاز در دیتابیس"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # جدول کاربران
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    phone_number TEXT,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_telethon_connected BOOLEAN DEFAULT FALSE,
                    session_file TEXT,
                    calendar_connected BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول پیام‌های شناسایی شده
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS detected_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    message_text TEXT,
                    detected_keywords TEXT,
                    is_confirmed BOOLEAN DEFAULT FALSE,
                    calendar_event_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
                )
            ''')
            
            # جدول جلسات ثبت شده
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_id TEXT UNIQUE,
                    title TEXT,
                    description TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    calendar_link TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
                )
            ''')
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def add_user(self, telegram_id: int, phone_number: str = None, 
                 username: str = None, first_name: str = None, last_name: str = None) -> bool:
        """اضافه کردن کاربر جدید"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO users 
                    (telegram_id, phone_number, username, first_name, last_name, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (telegram_id, phone_number, username, first_name, last_name, datetime.now()))
                conn.commit()
                logger.info(f"User {telegram_id} added/updated successfully")
                return True
        except Exception as e:
            logger.error(f"Error adding user {telegram_id}: {e}")
            return False
    
    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات کاربر"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user {telegram_id}: {e}")
            return None
    
    def update_telethon_status(self, telegram_id: int, is_connected: bool, session_file: str = None) -> bool:
        """به‌روزرسانی وضعیت اتصال Telethon"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET is_telethon_connected = ?, session_file = ?, updated_at = ?
                    WHERE telegram_id = ?
                ''', (is_connected, session_file, datetime.now(), telegram_id))
                conn.commit()
                logger.info(f"Telethon status updated for user {telegram_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating telethon status for user {telegram_id}: {e}")
            return False
    
    def update_calendar_status(self, telegram_id: int, is_connected: bool) -> bool:
        """به‌روزرسانی وضعیت اتصال تقویم"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET calendar_connected = ?, updated_at = ?
                    WHERE telegram_id = ?
                ''', (is_connected, datetime.now(), telegram_id))
                conn.commit()
                logger.info(f"Calendar status updated for user {telegram_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating calendar status for user {telegram_id}: {e}")
            return False
    
    def add_detected_message(self, user_id: int, chat_id: int, message_text: str, 
                           detected_keywords: str) -> int:
        """اضافه کردن پیام شناسایی شده"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO detected_messages 
                    (user_id, chat_id, message_text, detected_keywords)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, chat_id, message_text, detected_keywords))
                conn.commit()
                message_id = cursor.lastrowid
                logger.info(f"Detected message added for user {user_id}")
                return message_id
        except Exception as e:
            logger.error(f"Error adding detected message for user {user_id}: {e}")
            return None
    
    def confirm_message(self, message_id: int, calendar_event_id: str = None) -> bool:
        """تایید پیام شناسایی شده"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE detected_messages 
                    SET is_confirmed = TRUE, calendar_event_id = ?
                    WHERE id = ?
                ''', (calendar_event_id, message_id))
                conn.commit()
                logger.info(f"Message {message_id} confirmed")
                return True
        except Exception as e:
            logger.error(f"Error confirming message {message_id}: {e}")
            return False
    
    def add_calendar_event(self, user_id: int, event_id: str, title: str, 
                          description: str, start_time: datetime, end_time: datetime, 
                          calendar_link: str = None) -> bool:
        """اضافه کردن رویداد تقویم"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO calendar_events 
                    (user_id, event_id, title, description, start_time, end_time, calendar_link)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, event_id, title, description, start_time, end_time, calendar_link))
                conn.commit()
                logger.info(f"Calendar event added for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"Error adding calendar event for user {user_id}: {e}")
            return False
    
    def get_all_users(self) -> list:
        """دریافت لیست تمام کاربران"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users')
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
