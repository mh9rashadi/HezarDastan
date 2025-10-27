#!/usr/bin/env python3
"""
دستیار هوشمند تنظیم جلسه
Smart Meeting Assistant

این پروژه ترکیبی از ربات تلگرام، کلاینت Telethon و Google Calendar API است
که به صورت خودکار جلسات را از روی چت‌های تلگرام تشخیص و ثبت می‌کند.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Optional

# اضافه کردن مسیر پروژه به sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'calendar'))

from dotenv import load_dotenv
from bot.main import TelegramBot
from telethon_client.manager import TelethonManager
from calendar_api import GoogleCalendarManager
from database.db import DatabaseManager

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class MeetingAssistant:
    """کلاس اصلی دستیار هوشمند جلسه"""
    
    def __init__(self):
        self.bot: Optional[TelegramBot] = None
        self.telethon_manager: Optional[TelethonManager] = None
        self.calendar_manager: Optional[GoogleCalendarManager] = None
        self.db: Optional[DatabaseManager] = None
        
        # بارگذاری متغیرهای محیطی
        load_dotenv('config.env')
        
        # تنظیمات
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = os.getenv("TELEGRAM_API_HASH")
        self.service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID")
        
        # بررسی تنظیمات
        self._validate_config()
    
    def _validate_config(self):
        """بررسی صحت تنظیمات"""
        required_vars = [
            ("TELEGRAM_BOT_TOKEN", self.bot_token),
            ("TELEGRAM_API_ID", self.api_id),
            ("TELEGRAM_API_HASH", self.api_hash),
            ("GOOGLE_SERVICE_ACCOUNT_FILE", self.service_account_file),
            ("GOOGLE_CALENDAR_ID", self.calendar_id)
        ]
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please check your .env file or environment variables")
            sys.exit(1)
        
        logger.info("Configuration validation successful")
    
    async def initialize(self):
        """راه‌اندازی اولیه تمام سرویس‌ها"""
        try:
            logger.info("Initializing Meeting Assistant...")
            
            # ایجاد دایرکتوری logs
            os.makedirs("logs", exist_ok=True)
            
            # راه‌اندازی دیتابیس
            self.db = DatabaseManager()
            logger.info("✅ Database initialized")
            
            # راه‌اندازی Google Calendar
            self.calendar_manager = GoogleCalendarManager(
                self.service_account_file, 
                self.calendar_id
            )
            
            if self.calendar_manager.test_connection():
                logger.info("✅ Google Calendar connected")
            else:
                logger.warning("⚠️ Google Calendar connection failed")
            
            # راه‌اندازی Telethon Manager
            self.telethon_manager = TelethonManager(
                self.api_id, 
                self.api_hash
            )
            logger.info("✅ Telethon Manager initialized")
            
            # راه‌اندازی ربات تلگرام
            self.bot = TelegramBot(
                self.bot_token, 
                self.api_id, 
                self.api_hash
            )
            logger.info("✅ Telegram Bot initialized")
            
            # اتصال ربات به Telethon Manager
            self._connect_bot_to_telethon()
            
            logger.info("🎉 Meeting Assistant initialized successfully!")
            
        except Exception as e:
            logger.error(f"Error initializing Meeting Assistant: {e}")
            raise
    
    def _connect_bot_to_telethon(self):
        """اتصال ربات به Telethon Manager"""
        if self.bot and self.telethon_manager:
            # اضافه کردن متدهای Telethon به ربات
            self.bot.telethon_manager = self.telethon_manager
            self.bot.calendar_manager = self.calendar_manager
            
            logger.info("Bot connected to Telethon Manager")
    
    async def start_telethon_for_user(self, user_id: int, phone_number: str) -> bool:
        """شروع مانیتورینگ Telethon برای کاربر"""
        try:
            if not self.telethon_manager:
                logger.error("Telethon Manager not initialized")
                return False
            
            success = await self.telethon_manager.start_monitoring(user_id, phone_number)
            
            if success:
                # به‌روزرسانی وضعیت در دیتابیس
                self.db.update_telethon_status(user_id, True, f"user_{user_id}.session")
                logger.info(f"Telethon monitoring started for user {user_id}")
            else:
                logger.error(f"Failed to start Telethon monitoring for user {user_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error starting Telethon for user {user_id}: {e}")
            return False
    
    async def create_meeting_from_detection(self, user_id: int, message_text: str, 
                                          chat_id: int) -> Optional[dict]:
        """ایجاد جلسه از تشخیص پیام"""
        try:
            if not self.calendar_manager:
                logger.error("Calendar Manager not initialized")
                return None
            
            # دریافت اطلاعات کاربر
            user_data = self.db.get_user(user_id)
            if not user_data:
                logger.error(f"User {user_id} not found in database")
                return None
            
            # دریافت اطلاعات چت
            chat_info = await self.telethon_manager.get_chat_info(user_id, chat_id)
            user_name = chat_info.get('title', 'کاربر') if chat_info else 'کاربر'
            
            # ایجاد جلسه
            event = self.calendar_manager.create_meeting_from_message(message_text, user_name)
            
            if event:
                # ذخیره در دیتابیس
                self.db.add_calendar_event(
                    user_id=user_id,
                    event_id=event['id'],
                    title=event['title'],
                    description=event['description'],
                    start_time=event['start_time'],
                    end_time=event['end_time'],
                    calendar_link=event['html_link']
                )
                
                logger.info(f"Meeting created for user {user_id}: {event['html_link']}")
                return event
            else:
                logger.error(f"Failed to create meeting for user {user_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating meeting for user {user_id}: {e}")
            return None
    
    async def send_meeting_confirmation(self, user_id: int, message_text: str, 
                                      chat_id: int, message_id: int):
        """ارسال تایید جلسه به کاربر"""
        try:
            if not self.bot:
                logger.error("Bot not initialized")
                return
            
            await self.bot.send_meeting_detection_message(user_id, message_text, chat_id)
            logger.info(f"Meeting confirmation sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending meeting confirmation to user {user_id}: {e}")
    
    async def run(self):
        """اجرای اصلی برنامه"""
        try:
            await self.initialize()
            
            logger.info("🚀 Starting Meeting Assistant...")
            logger.info("Press Ctrl+C to stop")
            
            # اجرای ربات در پس‌زمینه
            bot_task = asyncio.create_task(self.bot.start_polling())
            
            # نگه داشتن برنامه در حال اجرا
            await bot_task
            
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down Meeting Assistant...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """پاکسازی منابع"""
        try:
            logger.info("Cleaning up resources...")
            
            if self.telethon_manager:
                await self.telethon_manager.cleanup()
                logger.info("✅ Telethon Manager cleaned up")
            
            logger.info("✅ Cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    """تابع اصلی"""
    print("""
    Smart Meeting Assistant
    
    This program combines:
    • Telegram Bot for user interaction
    • Telethon for message monitoring
    • Google Calendar API for meeting scheduling
    
    To start, configure config.env file and run the program.
    """)
    
    # ایجاد و اجرای دستیار
    assistant = MeetingAssistant()
    
    try:
        asyncio.run(assistant.run())
    except KeyboardInterrupt:
        print("\n👋 برنامه متوقف شد.")
    except Exception as e:
        print(f"❌ خطا در اجرای برنامه: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
