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
        self.pending_phone_code_hash: Dict[int, Any] = {}  # ✅ ذخیره کل result object
        self.bot = None
        
        os.makedirs(session_dir, exist_ok=True)
        
        self.meeting_keywords = [
            'جلسه', 'قرار', 'meeting', 'appointment', 'session',
            'میتینگ', 'ملاقات', 'دیدار', 'نشست', 'کنفرانس',
            'conference', 'call', 'تماس', 'zoom', 'skype'
        ]
        
        self.time_patterns = [
            r'(\d{1,2}):(\d{2})',
            r'(\d{1,2})\.(\d{2})',
            r'(\d{1,2})/(\d{2})',
            r'ساعت\s*(\d{1,2})',
            r'(\d{1,2})\s*ساعت',
        ]
    
    async def create_client(self, user_id: int, phone_number: str = None) -> Optional[TelegramClient]:
        """ایجاد کلاینت Telethon برای کاربر"""
        try:
            session_path = os.path.join(self.session_dir, f"user_{user_id}")
            
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()
            
            if await client.is_user_authorized():
                logger.info(f"✅ User {user_id} already authorized from saved session")
                self.clients[user_id] = client
                
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
        ارسال کد ورود به شماره کاربر
        """
        try:
            logger.info(f"📱 Sending login code to user {user_id} (phone: {phone_number})")
            
            # ✅ اگر client وجود داره و authorized هست، نیازی به کد جدید نیست
            if user_id in self.clients:
                client = self.clients[user_id]
                if await client.is_user_authorized():
                    logger.info(f"✅ User {user_id} already authorized")
                    return True
            
            # ✅ حذف client قبلی اگر وجود داره
            if user_id in self.clients:
                try:
                    await self.clients[user_id].disconnect()
                except:
                    pass
                del self.clients[user_id]
            
            # ✅ ساخت client جدید
            client = await self.create_client(user_id, phone_number)
            if client is None:
                logger.error(f"❌ Failed to create client for user {user_id}")
                return False
            
            # ذخیره شماره
            self.pending_phones[user_id] = phone_number
            
            # ✅ درخواست کد
            try:
                sent_code = await client.send_code_request(phone_number, force_sms=force_sms)
                
                # ✅ ذخیره phone_code_hash
                self.pending_phone_code_hash[user_id] = sent_code
                
                logger.info(f"✅ Code sent to user {user_id}")
                logger.debug(f"Code type: {sent_code.type}")
                
                return True
                
            except Exception as e:
                if 'force_sms' in str(e).lower():
                    logger.warning(f"⚠️ Retrying without force_sms")
                    sent_code = await client.send_code_request(phone_number)
                    self.pending_phone_code_hash[user_id] = sent_code
                    return True
                else:
                    raise

        except PhoneNumberInvalidError:
            logger.error(f"❌ Invalid phone number: {phone_number}")
            return False

        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait: {e.seconds}s")
            return False

        except Exception as e:
            logger.error(f"🔥 Error sending code: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def confirm_login_code(self, user_id: int, code: str = None, password: str = None) -> Dict[str, Any]:
        """
        تأیید کد ورود
        """
        try:
            logger.info(f"🔐 Confirming login for user {user_id}")
            
            # بررسی client
            if user_id not in self.clients:
                logger.error(f"❌ No client for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'client_not_found'}
            
            client = self.clients[user_id]
            
            # بررسی شماره
            phone = self.pending_phones.get(user_id)
            if not phone:
                logger.error(f"❌ No phone for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'no_pending_phone'}
            
            # اطمینان از اتصال
            if not client.is_connected():
                await client.connect()
            
            try:
                if code is not None:
                    # ✅ استفاده از phone_code_hash object
                    sent_code = self.pending_phone_code_hash.get(user_id)
                    if not sent_code:
                        logger.error(f"❌ No sent_code object for user {user_id}")
                        return {'ok': False, 'need_password': False, 'error': 'no_code_hash'}
                    
                    logger.info(f"🔑 Signing in with code for user {user_id}")
                    
                    # ✅ استفاده صحیح از sign_in
                    await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
                    
                elif password is not None:
                    logger.info(f"🔐 Signing in with 2FA password")
                    await client.sign_in(password=password)
                    
                else:
                    return {'ok': False, 'need_password': False, 'error': 'missing_credentials'}
                
            except SessionPasswordNeededError:
                logger.info(f"🔒 2FA required for user {user_id}")
                return {'ok': False, 'need_password': True, 'error': None}
            
            except PhoneCodeInvalidError:
                logger.error(f"❌ Invalid code for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            
            except PhoneCodeExpiredError:
                logger.error(f"⌛ Code expired for user {user_id}")
                self.pending_phone_code_hash.pop(user_id, None)
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            
            # ✅ ورود موفق
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.handle_message(event, user_id)
            
            # به‌روزرسانی دیتابیس
            session_file = os.path.join(self.session_dir, f"user_{user_id}.session")
            self.db.update_telethon_status(user_id, True, session_file)
            
            # پاکسازی
            self.pending_phones.pop(user_id, None)
            self.pending_phone_code_hash.pop(user_id, None)
            
            logger.info(f"✅ User {user_id} logged in successfully!")
            
            return {'ok': True, 'need_password': False, 'error': None}
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if 'expired' in error_msg or 'code_hash_invalid' in error_msg:
                logger.error(f"⌛ Code issue for user {user_id}: {e}")
                self.pending_phone_code_hash.pop(user_id, None)
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            
            elif 'invalid' in error_msg:
                logger.error(f"❌ Invalid code for user {user_id}: {e}")
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            
            else:
                logger.error(f"🔥 Unexpected error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return {'ok': False, 'need_password': False, 'error': str(e)}
    
    async def handle_message(self, event, user_id: int):
        """پردازش پیام‌های دریافتی"""
        try:
            message = event.message
            chat = await event.get_chat()
            
            if not message.text:
                return
            
            message_text = message.text.lower()
            
            detected_keywords = []
            for keyword in self.meeting_keywords:
                if keyword.lower() in message_text:
                    detected_keywords.append(keyword)
            
            if detected_keywords:
                logger.info(f"🔍 Meeting detected for user {user_id}: {detected_keywords}")
                
                message_id = self.db.add_detected_message(
                    user_id=user_id,
                    chat_id=chat.id,
                    message_text=message.text,
                    detected_keywords=", ".join(detected_keywords)
                )
                
                if self.bot:
                    await self.bot.send_meeting_detection_message(
                        user_id, 
                        message.text, 
                        chat.id
                    )
                
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
    
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
            logger.error(f"❌ Error disconnecting: {e}")
            return False
    
    async def is_user_connected(self, user_id: int) -> bool:
        """بررسی اتصال"""
        if user_id not in self.clients:
            return False
        
        client = self.clients[user_id]
        return client.is_connected() and await client.is_user_authorized()
    
    async def start_monitoring(self, user_id: int, phone_number: str) -> bool:
        """شروع مانیتورینگ"""
        try:
            session_file = os.path.join(self.session_dir, f"user_{user_id}.session")
            
            if os.path.exists(session_file):
                logger.info(f"📂 Found session for user {user_id}")
                client = await self.create_client(user_id, phone_number)
                
                if client and await client.is_user_authorized():
                    logger.info(f"✅ User {user_id} reconnected")
                    return True
            
            logger.info(f"🔄 Fresh monitoring for user {user_id}")
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
            logger.info("✅ Cleanup done")
            
        except Exception as e:
            logger.error(f"❌ Error cleanup: {e}")