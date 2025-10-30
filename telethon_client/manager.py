import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError, PhoneNumberInvalidError
from telethon.tl.types import User, Chat, Channel
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from database.db import DatabaseManager

logger = logging.getLogger(__name__)

class TelethonManager:
    def __init__(self, api_id: int, api_hash: str, session_dir: str = "telethon_client/sessions"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_dir = session_dir
        self.db = DatabaseManager()
        self.clients: Dict[int, TelegramClient] = {}
        self.pending_phones: Dict[int, str] = {}
        self.pending_code_hash: Dict[int, str] = {}
        
        # ایجاد دایرکتوری sessions
        os.makedirs(session_dir, exist_ok=True)
        
        # کلمات کلیدی برای تشخیص جلسات
        self.meeting_keywords = [
            'جلسه', 'قرار', 'meeting', 'appointment', 'session',
            'میتینگ', 'ملاقات', 'دیدار', 'نشست', 'کنفرانس',
            'conference', 'call', 'تماس', 'zoom', 'skype'
        ]
        
        # الگوهای زمانی
        self.time_patterns = [
            r'(\d{1,2}):(\d{2})',  # 14:30
            r'(\d{1,2})\.(\d{2})',  # 14.30
            r'(\d{1,2})/(\d{2})',  # 14/30
            r'ساعت\s*(\d{1,2})',   # ساعت 14
            r'(\d{1,2})\s*ساعت',   # 14 ساعت
        ]
    
    async def create_client(self, user_id: int, phone_number: str) -> Optional[TelegramClient]:
        """ایجاد کلاینت Telethon برای کاربر"""
        try:
            session_path = os.path.join(self.session_dir, f"user_{user_id}.session")
            
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            # start() would try to drive interactive login; we attach after explicit sign in
            await client.connect()
            if not await client.is_user_authorized():
                logger.debug("Client created but not authorized yet for user %s", user_id)
            
            self.clients[user_id] = client
            
            # ثبت event handler برای پیام‌های جدید
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.handle_message(event, user_id)
            
            logger.info(f"Telethon client created for user {user_id}")
            return client
            
        except Exception as e:
            logger.error(f"Error creating Telethon client for user {user_id}: {e}")
            return None

        async def send_login_code(self, user_id: int, phone_number: str) -> bool:
        """
        ارسال کد ورود به شماره کاربر از طریق Telethon (سازگار با نسخه‌های جدید).
        """
        try:
            # ایجاد کلاینت مخصوص این کاربر
            client = await self.create_client(user_id, phone_number)
            if client is None:
                logger.error(f"❌ Client creation failed for user {user_id}")
                return False

            # ذخیره شماره موقت برای کاربر
            self.pending_phones[user_id] = phone_number

            # درخواست ارسال کد به کاربر (Telethon خودش تصمیم می‌گیره کد از طریق تلگرام یا SMS بیاد)
            result = await client.send_code_request(phone_number)

            # ذخیره phone_code_hash برای استفاده بعدی در sign_in
            self.pending_code_hash[user_id] = getattr(result, 'phone_code_hash', None)

            logger.info(f"✅ Login code requested for user {user_id} ({phone_number})")
            return True

        except PhoneNumberInvalidError:
            logger.error(f"❌ Invalid phone number for user {user_id}: {phone_number}")
            return False

        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait ({e.seconds}s) while sending code for user {user_id}")
            return False

        except Exception as e:
            logger.error(f"🔥 Unexpected error while sending login code for user {user_id}: {e}")
            return False


    async def confirm_login_code(self, user_id: int, code: str | None = None, password: str | None = None) -> Dict[str, Any]:
        """تأیید کد ورود و تکمیل ورود.
        خروجی:
        { 'ok': bool, 'need_password': bool, 'error': Optional[str] }
        """
        try:
            if user_id not in self.clients:
                logger.error("Client not initialized for user %s", user_id)
                return { 'ok': False, 'need_password': False, 'error': 'client_not_initialized' }
            client = self.clients[user_id]
            phone = self.pending_phones.get(user_id)
            if not phone:
                logger.error("No pending phone number for user %s", user_id)
                return { 'ok': False, 'need_password': False, 'error': 'no_pending_phone' }

            try:
                if code is not None:
                    pch = self.pending_code_hash.get(user_id)
                    await client.sign_in(phone=phone, code=code, phone_code_hash=pch)
                elif password is not None:
                    # If only password provided (after SessionPasswordNeeded), try password sign-in
                    await client.sign_in(password=password)
                else:
                    return { 'ok': False, 'need_password': False, 'error': 'missing_code_or_password' }
            except SessionPasswordNeededError:
                # Password needed; caller should ask for it
                logger.info("2FA password required for user %s", user_id)
                return { 'ok': False, 'need_password': True, 'error': None }

            # Mark connected and add handlers
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.handle_message(event, user_id)

            self.db.update_telethon_status(user_id, True, os.path.join(self.session_dir, f"user_{user_id}.session"))
            logger.info("User %s authorized successfully", user_id)
            # Cleanup pending phone
            self.pending_phones.pop(user_id, None)
            self.pending_code_hash.pop(user_id, None)
            return { 'ok': True, 'need_password': False, 'error': None }
        except PhoneCodeInvalidError:
            logger.error("Invalid login code for user %s", user_id)
            return { 'ok': False, 'need_password': False, 'error': 'invalid_code' }
        except Exception as e:
            msg = str(e)
            if 'expired' in msg.lower():
                # Hint caller to resend
                return { 'ok': False, 'need_password': False, 'error': 'code_expired' }
            logger.error(f"Error confirming login code for user {user_id}: {e}")
            return { 'ok': False, 'need_password': False, 'error': str(e) }
    
    async def handle_message(self, event, user_id: int):
        """پردازش پیام‌های دریافتی"""
        try:
            message = event.message
            chat = await event.get_chat()
            
            # فقط پیام‌های متنی را پردازش می‌کنیم
            if not message.text:
                return
            
            message_text = message.text.lower()
            
            # بررسی وجود کلمات کلیدی
            detected_keywords = []
            for keyword in self.meeting_keywords:
                if keyword.lower() in message_text:
                    detected_keywords.append(keyword)
            
            if detected_keywords:
                logger.info(f"Meeting keywords detected for user {user_id}: {detected_keywords}")
                
                # ذخیره پیام شناسایی شده در دیتابیس
                message_id = self.db.add_detected_message(
                    user_id=user_id,
                    chat_id=chat.id,
                    message_text=message.text,
                    detected_keywords=", ".join(detected_keywords)
                )
                
                # ارسال پیام تشخیص به کاربر از طریق ربات
                await self.send_detection_notification(user_id, message.text, chat.id, message_id)
                
        except Exception as e:
            logger.error(f"Error handling message for user {user_id}: {e}")
    
    async def send_detection_notification(self, user_id: int, message_text: str, chat_id: int, message_id: int):
        """ارسال اطلاعیه تشخیص جلسه"""
        try:
            # اینجا باید با ربات تلگرام ارتباط برقرار کنیم
            # فعلاً فقط در لاگ ثبت می‌کنیم
            logger.info(f"Sending detection notification to user {user_id}")
            
            # TODO: ارسال پیام از طریق ربات تلگرام
            # bot.send_meeting_detection_message(user_id, message_text, chat_id)
            
        except Exception as e:
            logger.error(f"Error sending detection notification: {e}")
    
    async def extract_time_from_message(self, message_text: str) -> Optional[Dict[str, Any]]:
        """استخراج زمان از پیام"""
        try:
            for pattern in self.time_patterns:
                match = re.search(pattern, message_text)
                if match:
                    if ':' in pattern or '.' in pattern or '/' in pattern:
                        hour = int(match.group(1))
                        minute = int(match.group(2))
                    else:
                        hour = int(match.group(1))
                        minute = 0
                    
                    # ایجاد زمان برای امروز
                    now = datetime.now()
                    event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    
                    # اگر زمان گذشته است، برای فردا تنظیم کن
                    if event_time <= now:
                        event_time += timedelta(days=1)
                    
                    return {
                        'start_time': event_time,
                        'end_time': event_time + timedelta(hours=1),  # پیش‌فرض 1 ساعت
                        'extracted_time': f"{hour}:{minute:02d}"
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting time from message: {e}")
            return None
    
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات کاربر از Telethon"""
        try:
            if user_id not in self.clients:
                return None
            
            client = self.clients[user_id]
            me = await client.get_me()
            
            return {
                'id': me.id,
                'username': me.username,
                'first_name': me.first_name,
                'last_name': me.last_name,
                'phone': me.phone,
                'is_bot': me.bot
            }
            
        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
            return None
    
    async def get_chat_info(self, user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات چت"""
        try:
            if user_id not in self.clients:
                return None
            
            client = self.clients[user_id]
            chat = await client.get_entity(chat_id)
            
            if isinstance(chat, User):
                return {
                    'id': chat.id,
                    'type': 'user',
                    'title': f"{chat.first_name} {chat.last_name or ''}".strip(),
                    'username': chat.username
                }
            elif isinstance(chat, (Chat, Channel)):
                return {
                    'id': chat.id,
                    'type': 'group' if isinstance(chat, Chat) else 'channel',
                    'title': chat.title,
                    'username': getattr(chat, 'username', None)
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting chat info for {user_id}, {chat_id}: {e}")
            return None
    
    async def send_message(self, user_id: int, chat_id: int, text: str) -> bool:
        """ارسال پیام از طریق Telethon"""
        try:
            if user_id not in self.clients:
                return False
            
            client = self.clients[user_id]
            await client.send_message(chat_id, text)
            
            logger.info(f"Message sent to {chat_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending message for user {user_id}: {e}")
            return False
    
    async def disconnect_user(self, user_id: int) -> bool:
        """قطع اتصال کاربر"""
        try:
            if user_id in self.clients:
                await self.clients[user_id].disconnect()
                del self.clients[user_id]
                
                # به‌روزرسانی وضعیت در دیتابیس
                self.db.update_telethon_status(user_id, False)
                
                logger.info(f"User {user_id} disconnected from Telethon")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error disconnecting user {user_id}: {e}")
            return False
    
    async def get_all_connected_users(self) -> List[int]:
        """دریافت لیست تمام کاربران متصل"""
        return list(self.clients.keys())
    
    async def is_user_connected(self, user_id: int) -> bool:
        """بررسی اتصال کاربر"""
        return user_id in self.clients and self.clients[user_id].is_connected()
    
    async def start_monitoring(self, user_id: int, phone_number: str) -> bool:
        """شروع مانیتورینگ برای کاربر"""
        try:
            if user_id in self.clients:
                logger.info(f"User {user_id} is already connected")
                return True
            
            client = await self.create_client(user_id, phone_number)
            if client:
                logger.info(f"Started monitoring for user {user_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error starting monitoring for user {user_id}: {e}")
            return False
    
    async def stop_monitoring(self, user_id: int) -> bool:
        """توقف مانیتورینگ برای کاربر"""
        return await self.disconnect_user(user_id)
    
    async def cleanup(self):
        """پاکسازی و بستن تمام اتصالات"""
        try:
            for user_id, client in self.clients.items():
                await client.disconnect()
            
            self.clients.clear()
            logger.info("All Telethon connections cleaned up")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# تابع اصلی برای تست
async def main():
    """تابع اصلی برای تست Telethon"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv('config.env')
    
    api_id = int(os.getenv("TELEGRAM_API_ID"))
    api_hash = os.getenv("TELEGRAM_API_HASH")
    
    if not api_id or not api_hash:
        logger.error("Missing API credentials!")
        return
    
    manager = TelethonManager(api_id, api_hash)
    
    try:
        # تست اتصال
        print("Telethon Manager initialized successfully!")
        
        # نگه داشتن برنامه در حال اجرا
        await asyncio.sleep(3600)  # 1 ساعت
        
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
