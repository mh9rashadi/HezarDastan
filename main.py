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

from dotenv import load_dotenv
from bot.main import TelegramBot
from telethon_client.manager import TelethonManager
from calendar.calendar_api import GoogleCalendarManager  # ✅ اصلاح شد
from database.db import DatabaseManager

# تنظیمات لاگینگ
os.makedirs("logs", exist_ok=True)
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
        load_dotenv('.env')  # ✅ اضافه شد برای پشتیبانی از .env
        
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
        ]
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value or (var_name == "TELEGRAM_API_ID" and var_value == 0):
                missing_vars.append(var_name)
        
        if missing_vars:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please check your .env file or config.env file")
            sys.exit(1)
        
        # ✅ Google Calendar اختیاری است
        if not self.service_account_file or not self.calendar_id:
            logger.warning("⚠️ Google Calendar credentials not found. Calendar features will be disabled.")
        
        logger.info("✅ Configuration validation successful")
    
    async def initialize(self):
        """راه‌اندازی اولیه تمام سرویس‌ها"""
        try:
            logger.info("🚀 Initializing Meeting Assistant...")
            
            # ایجاد دایرکتوری‌های مورد نیاز
            os.makedirs("logs", exist_ok=True)
            os.makedirs("telethon_client/sessions", exist_ok=True)
            os.makedirs("database", exist_ok=True)
            
            # راه‌اندازی دیتابیس
            self.db = DatabaseManager()
            logger.info("✅ Database initialized")
            
            # راه‌اندازی Google Calendar (اختیاری)
            if self.service_account_file and self.calendar_id:
                try:
                    self.calendar_manager = GoogleCalendarManager(
                        self.service_account_file, 
                        self.calendar_id
                    )
                    
                    if self.calendar_manager.test_connection():
                        logger.info("✅ Google Calendar connected")
                    else:
                        logger.warning("⚠️ Google Calendar connection failed")
                        self.calendar_manager = None
                except Exception as e:
                    logger.warning(f"⚠️ Google Calendar initialization failed: {e}")
                    self.calendar_manager = None
            else:
                logger.info("⏭️ Google Calendar skipped (credentials not provided)")
            
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
            
            # ✅ اتصال سرویس‌ها به ربات
            self.bot.telethon_manager = self.telethon_manager
            self.bot.calendar_manager = self.calendar_manager
            self.bot.db = self.db
            
            # ✅ اتصال ربات به Telethon برای نوتیفیکیشن‌ها
            self.telethon_manager.bot = self.bot
            
            logger.info("✅ Telegram Bot initialized")
            logger.info("🎉 Meeting Assistant initialized successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error initializing Meeting Assistant: {e}")
            raise
    
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
                logger.info(f"✅ Telethon monitoring started for user {user_id}")
            else:
                logger.error(f"❌ Failed to start Telethon monitoring for user {user_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error starting Telethon for user {user_id}: {e}")
            return False
    
    async def create_meeting_from_detection(self, user_id: int, message_text: str, 
                                          chat_id: int) -> Optional[dict]:
        """ایجاد جلسه از تشخیص پیام"""
        try:
            if not self.calendar_manager:
                logger.warning("Calendar Manager not initialized - skipping meeting creation")
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
                
                logger.info(f"✅ Meeting created for user {user_id}: {event['html_link']}")
                return event
            else:
                logger.error(f"❌ Failed to create meeting for user {user_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error creating meeting for user {user_id}: {e}")
            return None
    
    async def run(self):
        """اجرای اصلی برنامه"""
        try:
            await self.initialize()
            
            logger.info("🚀 Starting Meeting Assistant...")
            logger.info("📱 Bot is ready to receive messages")
            logger.info("Press Ctrl+C to stop")
            
            # اجرای ربات
            await self.bot.start_polling()
            
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down Meeting Assistant...")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """پاکسازی منابع"""
        try:
            logger.info("🧹 Cleaning up resources...")
            
            if self.telethon_manager:
                await self.telethon_manager.cleanup()
                logger.info("✅ Telethon Manager cleaned up")
            
            logger.info("✅ Cleanup completed")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

def main():
    """تابع اصلی"""
    print("""
    ╔════════════════════════════════════════╗
    ║   🤖 Smart Meeting Assistant 🤖       ║
    ╠════════════════════════════════════════╣
    ║  Telegram Bot + Telethon + Calendar   ║
    ║                                        ║
    ║  This program monitors your Telegram  ║
    ║  messages and automatically schedules ║
    ║  meetings in Google Calendar.         ║
    ╚════════════════════════════════════════╝
    """)
    
    # ایجاد و اجرای دستیار
    assistant = MeetingAssistant()
    
    try:
        asyncio.run(assistant.run())
    except KeyboardInterrupt:
        print("\n👋 برنامه متوقف شد.")
    except Exception as e:
        print(f"❌ خطا در اجرای برنامه: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()