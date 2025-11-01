import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneCodeExpiredError,
    FloodWaitError, 
    PhoneNumberInvalidError
)
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
        self.bot = None  # ✅ اضافه شد برای ارتباط با ربات
        
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
    
    async def create_client(self, user_id: int, phone_number: str = None) -> Optional[TelegramClient]:
        """ایجاد کلاینت Telethon برای کاربر"""
        try:
            session_path = os.path.join(self.session_dir, f"user_{user_id}")
            
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()
            
            # ✅ بررسی اگر قبلاً authorized شده
            if await client.is_user_authorized():
                logger.info(f"✅ User {user_id} already authorized from saved session")
                self.clients[user_id] = client
                
                # ثبت event handler
                @client.on(events.NewMessage(incoming=True))
                async def handle_new_message(event):
                    await self.handle_message(event, user_id)
                
                return client
            else:
                logger.debug(f"Client created but not authorized yet for user {user_id}")
                self.clients[user_id] = client
                return client
            
        except Exception as e:
            logger.error(f"❌ Error creating Telethon client for user {user_id}: {e}")
            return None

    async def send_login_code(self, user_id: int, phone_number: str, force_sms: bool = False) -> bool:
        """
        ارسال کد ورود به شماره کاربر از طریق Telethon
        """
        try:
            logger.info(f"📱 Sending login code to user {user_id} (phone: {phone_number}, force_sms: {force_sms})")
            
            # ✅ اگر client وجود نداره، بسازش
            if user_id not in self.clients:
                client = await self.create_client(user_id, phone_number)
                if client is None:
                    logger.error(f"❌ Failed to create client for user {user_id}")
                    return False
            else:
                client = self.clients[user_id]
            
            # اطمینان از اتصال
            if not client.is_connected():
                await client.connect()
            
            # ذخیره شماره موقت
            self.pending_phones[user_id] = phone_number
            
            # ✅ ارسال کد (force_sms برای بار دوم)
            try:
                result = await client.send_code_request(phone_number, force_sms=force_sms)
            except Exception as e:
                # اگر خطای force_sms داد، بدون force_sms امتحان کن
                logger.warning(f"⚠️ force_sms failed, retrying without it: {e}")
                result = await client.send_code_request(phone_number)
            
            # ذخیره phone_code_hash
            self.pending_code_hash[user_id] = result.phone_code_hash
            
            logger.info(f"✅ Login code sent successfully to user {user_id}")
            logger.debug(f"Code hash saved: {result.phone_code_hash[:10]}...")
            
            return True

        except PhoneNumberInvalidError:
            logger.error(f"❌ Invalid phone number for user {user_id}: {phone_number}")
            return False

        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait ({e.seconds}s) for user {user_id}")
            return False

        except Exception as e:
            logger.error(f"🔥 Error sending login code to user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False


    async def confirm_login_code(self, user_id: int, code: str = None, password: str = None) -> Dict[str, Any]:
        """
        تأیید کد ورود و تکمیل ورود
        
        Returns:
            {
                'ok': bool,
                'need_password': bool,
                'error': Optional[str]
            }
        """
        try:
            logger.info(f"🔐 Confirming login for user {user_id}")
            
            # ✅ بررسی وجود client
            if user_id not in self.clients:
                logger.error(f"❌ No client found for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'client_not_found'}
            
            client = self.clients[user_id]
            
            # ✅ بررسی وجود شماره
            phone = self.pending_phones.get(user_id)
            if not phone:
                logger.error(f"❌ No pending phone for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'no_pending_phone'}
            
            # ✅ بررسی وجود code_hash
            phone_code_hash = self.pending_code_hash.get(user_id)
            if not phone_code_hash and code:
                logger.error(f"❌ No code hash found for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'no_code_hash'}
            
            # اطمینان از اتصال
            if not client.is_connected():
                await client.connect()
            
            # ✅ تلاش برای sign in
            try:
                if code is not None:
                    # ورود با کد
                    logger.info(f"🔑 Attempting sign in with code for user {user_id}")
                    logger.debug(f"Phone: {phone}, Code: {code}, Hash: {phone_code_hash[:10]}...")
                    
                    await client.sign_in(
                        phone=phone,
                        code=code,
                        phone_code_hash=phone_code_hash
                    )
                    
                elif password is not None:
                    # ورود با رمز 2FA
                    logger.info(f"🔐 Attempting sign in with 2FA password for user {user_id}")
                    await client.sign_in(password=password)
                    
                else:
                    logger.error(f"❌ Neither code nor password provided for user {user_id}")
                    return {'ok': False, 'need_password': False, 'error': 'missing_code_or_password'}
                
            except SessionPasswordNeededError:
                # نیاز به رمز 2FA
                logger.info(f"🔒 2FA password required for user {user_id}")
                return {'ok': False, 'need_password': True, 'error': None}
            
            except PhoneCodeInvalidError:
                logger.error(f"❌ Invalid code for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            
            except PhoneCodeExpiredError:
                logger.error(f"⌛ Code expired for user {user_id}")
                # ✅ پاک کردن code hash منقضی شده
                self.pending_code_hash.pop(user_id, None)
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            
            # ✅ ورود موفق - ثبت event handler
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.handle_message(event, user_id)
            
            # ✅ به‌روزرسانی دیتابیس
            session_file = os.path.join(self.session_dir, f"user_{user_id}.session")
            self.db.update_telethon_status(user_id, True, session_file)
            
            # ✅ پاک کردن اطلاعات موقت
            self.pending_phones.pop(user_id, None)
            self.pending_code_hash.pop(user_id, None)
            
            logger.info(f"✅ User {user_id} authorized successfully!")
            
            return {'ok': True, 'need_password': False, 'error': None}
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # ✅ شناسایی انواع خطاها
            if 'expired' in error_msg:
                logger.error(f"⌛ Code expired for user {user_id}")
                self.pending_code_hash.pop(user_id, None)
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            
            elif 'invalid' in error_msg:
                logger.error(f"❌ Invalid code for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            
            else:
                logger.error(f"🔥 Unexpected error confirming login for user {user_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return {'ok': False, 'need_password': False, 'error': str(e)}
    
    async def handle_message(self, event, user_id: int):
        """پردازش پیام‌های دریافتی"""
        try:
            message = event.message
            chat = await event.get_chat()
            
            # فقط پیام‌های متنی
            if not message.text:
                return
            
            message_text = message.text.lower()
            
            # بررسی کلمات کلیدی
            detected_keywords = []
            for keyword in self.meeting_keywords:
                if keyword.lower() in message_text:
                    detected_keywords.append(keyword)
            
            if detected_keywords:
                logger.info(f"🔍 Meeting keywords detected for user {user_id}: {detected_keywords}")
                
                # ذخیره در دیتابیس
                message_id = self.db.add_detected_message(
                    user_id=user_id,
                    chat_id=chat.id,
                    message_text=message.text,
                    detected_keywords=", ".join(detected_keywords)
                )
                
                # ✅ ارسال نوتیفیکیشن به ربات
                if self.bot:
                    await self.bot.send_meeting_detection_message(
                        user_id, 
                        message.text, 
                        chat.id
                    )
                else:
                    logger.warning("⚠️ Bot not connected to Telethon manager")
                
        except Exception as e:
            logger.error(f"❌ Error handling message for user {user_id}: {e}")
    
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
                    
                    now = datetime.now()
                    event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    
                    if event_time <= now:
                        event_time += timedelta(days=1)
                    
                    return {
                        'start_time': event_time,
                        'end_time': event_time + timedelta(hours=1),
                        'extracted_time': f"{hour}:{minute:02d}"
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extracting time: {e}")
            return None
    
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات کاربر"""
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
            logger.error(f"❌ Error getting user info: {e}")
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
            logger.error(f"❌ Error getting chat info: {e}")
            return None
    
    async def disconnect_user(self, user_id: int) -> bool:
        """قطع اتصال کاربر"""
        try:
            if user_id in self.clients:
                await self.clients[user_id].disconnect()
                del self.clients[user_id]
                
                self.db.update_telethon_status(user_id, False)
                
                logger.info(f"✅ User {user_id} disconnected")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error disconnecting user {user_id}: {e}")
            return False
    
    async def is_user_connected(self, user_id: int) -> bool:
        """بررسی اتصال کاربر"""
        if user_id not in self.clients:
            return False
        
        client = self.clients[user_id]
        return client.is_connected() and await client.is_user_authorized()
    
    async def start_monitoring(self, user_id: int, phone_number: str) -> bool:
        """شروع مانیتورینگ"""
        try:
            # ✅ بررسی session موجود
            session_file = os.path.join(self.session_dir, f"user_{user_id}.session")
            
            if os.path.exists(session_file):
                logger.info(f"📂 Found existing session for user {user_id}")
                client = await self.create_client(user_id, phone_number)
                
                if client and await client.is_user_authorized():
                    logger.info(f"✅ User {user_id} reconnected from saved session")
                    return True
            
            logger.info(f"🔄 Starting fresh monitoring for user {user_id}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error starting monitoring: {e}")
            return False
    
    async def cleanup(self):
        """پاکسازی"""
        try:
            for user_id, client in list(self.clients.items()):
                try:
                    await client.disconnect()
                except:
                    pass
            
            self.clients.clear()
            logger.info("✅ All connections cleaned up")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")