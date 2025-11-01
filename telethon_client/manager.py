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
    
    def _get_session_path(self, user_id: int) -> str:
        """دریافت مسیر session"""
        return os.path.join(self.session_dir, f"user_{user_id}")
    
    def _remove_session_files(self, user_id: int):
        """حذف کامل فایل‌های session"""
        try:
            session_path = self._get_session_path(user_id)
            
            # حذف تمام فایل‌های مرتبط
            for ext in ['', '.session', '.session-journal']:
                file_path = session_path + ext
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"🗑️ Removed: {file_path}")
            
            logger.info(f"🧹 Session files cleaned for user {user_id}")
            
        except Exception as e:
            logger.warning(f"⚠️ Error removing session files: {e}")
    
    async def create_client(self, user_id: int, fresh: bool = False) -> Optional[TelegramClient]:
        """ایجاد کلاینت Telethon"""
        try:
            session_path = self._get_session_path(user_id)
            
            # اگر fresh باشه، session قدیمی رو پاک کن
            if fresh:
                self._remove_session_files(user_id)
                logger.info(f"🆕 Creating fresh client for user {user_id}")
            
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()
            
            # بررسی authorization
            if await client.is_user_authorized():
                logger.info(f"✅ User {user_id} already authorized")
                self.clients[user_id] = client
                
                # ثبت event handler
                @client.on(events.NewMessage(incoming=True))
                async def handle_new_message(event):
                    await self.handle_message(event, user_id)
                
                return client
            else:
                logger.debug(f"📝 Client created but not authorized for user {user_id}")
                self.clients[user_id] = client
                return client
            
        except Exception as e:
            logger.error(f"❌ Error creating client: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def send_login_code(self, user_id: int, phone_number: str, force_sms: bool = False) -> bool:
        """
        ارسال کد ورود - با session تمیز
        """
        try:
            logger.info(f"📱 Sending login code to user {user_id}")
            logger.info(f"📞 Phone: {phone_number}, Force SMS: {force_sms}")
            
            # ✅ قطع و حذف client قبلی
            if user_id in self.clients:
                try:
                    await self.clients[user_id].disconnect()
                    logger.debug(f"🔌 Disconnected old client for user {user_id}")
                except:
                    pass
                del self.clients[user_id]
            
            # ✅ حذف session files قدیمی
            self._remove_session_files(user_id)
            
            # ✅ ایجاد client جدید
            client = await self.create_client(user_id, fresh=True)
            if not client:
                logger.error(f"❌ Failed to create client")
                return False
            
            # ذخیره شماره
            self.pending_phones[user_id] = phone_number
            
            # ✅ ارسال کد
            logger.info(f"📤 Requesting code for {phone_number}...")
            
            try:
                # سعی با force_sms
                if force_sms:
                    sent_code = await client.send_code_request(phone_number, force_sms=True)
                else:
                    sent_code = await client.send_code_request(phone_number)
                
                logger.info(f"✅ Code sent successfully!")
                logger.debug(f"📋 Code type: {sent_code.type}")
                
                return True
                
            except Exception as e:
                error_str = str(e)
                if 'PHONE_NUMBER_INVALID' in error_str:
                    logger.error(f"❌ Invalid phone number: {phone_number}")
                    return False
                elif 'force_sms' in error_str.lower():
                    # اگر مشکل force_sms داره، بدون force_sms امتحان کن
                    logger.warning(f"⚠️ force_sms not supported, retrying...")
                    sent_code = await client.send_code_request(phone_number)
                    logger.info(f"✅ Code sent (without force_sms)")
                    return True
                else:
                    raise

        except PhoneNumberInvalidError:
            logger.error(f"❌ Invalid phone number: {phone_number}")
            return False

        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait: {e.seconds} seconds")
            return False

        except Exception as e:
            logger.error(f"🔥 Error sending login code: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def confirm_login_code(self, user_id: int, code: str = None, password: str = None) -> Dict[str, Any]:
        """
        تأیید کد ورود یا رمز 2FA
        """
        try:
            logger.info(f"🔐 Confirming login for user {user_id}")
            
            # بررسی client
            if user_id not in self.clients:
                logger.error(f"❌ No active client for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'no_client'}
            
            client = self.clients[user_id]
            
            # بررسی شماره
            phone = self.pending_phones.get(user_id)
            if not phone:
                logger.error(f"❌ No pending phone for user {user_id}")
                return {'ok': False, 'need_password': False, 'error': 'no_phone'}
            
            # اطمینان از اتصال
            if not client.is_connected():
                logger.info(f"🔌 Reconnecting client...")
                await client.connect()
            
            # ✅ Sign in
            try:
                if code is not None:
                    # ورود با کد
                    logger.info(f"🔑 Signing in with code: {code}")
                    logger.debug(f"📞 Phone: {phone}")
                    
                    # ✅ فقط با phone و code
                    result = await client.sign_in(phone=phone, code=code)
                    
                    logger.info(f"✅ Sign in successful!")
                    
                elif password is not None:
                    # ورود با 2FA
                    logger.info(f"🔐 Signing in with 2FA password")
                    result = await client.sign_in(password=password)
                    
                    logger.info(f"✅ 2FA sign in successful!")
                    
                else:
                    logger.error(f"❌ No code or password provided")
                    return {'ok': False, 'need_password': False, 'error': 'missing_credentials'}
                
            except SessionPasswordNeededError:
                logger.info(f"🔒 2FA password required for user {user_id}")
                return {'ok': False, 'need_password': True, 'error': None}
            
            except PhoneCodeInvalidError as e:
                logger.error(f"❌ Invalid code: {e}")
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            
            except PhoneCodeExpiredError as e:
                logger.error(f"⌛ Code expired: {e}")
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            
            # ✅ ورود موفق - تنظیم event handler
            logger.info(f"🎉 User {user_id} logged in successfully!")
            
            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.handle_message(event, user_id)
            
            # به‌روزرسانی دیتابیس
            session_file = self._get_session_path(user_id) + ".session"
            self.db.update_telethon_status(user_id, True, session_file)
            
            # پاکسازی pending data
            self.pending_phones.pop(user_id, None)
            
            logger.info(f"✅ User {user_id} setup complete!")
            
            return {'ok': True, 'need_password': False, 'error': None}
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"🔥 Unexpected error: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            
            # تشخیص نوع خطا
            if 'CODE_INVALID' in error_msg or 'PHONE_CODE_INVALID' in error_msg:
                return {'ok': False, 'need_password': False, 'error': 'invalid_code'}
            elif 'CODE_EXPIRED' in error_msg or 'PHONE_CODE_EXPIRED' in error_msg:
                return {'ok': False, 'need_password': False, 'error': 'code_expired'}
            elif 'PASSWORD' in error_msg:
                return {'ok': False, 'need_password': True, 'error': None}
            else:
                return {'ok': False, 'need_password': False, 'error': error_msg}
    
    async def handle_message(self, event, user_id: int):
        """پردازش پیام‌های دریافتی"""
        try:
            message = event.message
            chat = await event.get_chat()
            
            if not message.text:
                return
            
            message_text = message.text.lower()
            
            # تشخیص کلمات کلیدی
            detected_keywords = []
            for keyword in self.meeting_keywords:
                if keyword.lower() in message_text:
                    detected_keywords.append(keyword)
            
            if detected_keywords:
                logger.info(f"🔍 Meeting detected: {detected_keywords}")
                
                # ذخیره در DB
                message_id = self.db.add_detected_message(
                    user_id=user_id,
                    chat_id=chat.id,
                    message_text=message.text,
                    detected_keywords=", ".join(detected_keywords)
                )
                
                # ارسال به ربات
                if self.bot:
                    await self.bot.send_meeting_detection_message(
                        user_id, 
                        message.text, 
                        chat.id
                    )
                else:
                    logger.warning(f"⚠️ Bot not connected")
                
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
    
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
                'phone': me.phone
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
        """بررسی اتصال کاربر"""
        if user_id not in self.clients:
            return False
        
        try:
            client = self.clients[user_id]
            return client.is_connected() and await client.is_user_authorized()
        except:
            return False
    
    async def start_monitoring(self, user_id: int, phone_number: str) -> bool:
        """شروع مانیتورینگ"""
        try:
            # بررسی session موجود
            session_file = self._get_session_path(user_id) + ".session"
            
            if os.path.exists(session_file):
                logger.info(f"📂 Found existing session for user {user_id}")
                client = await self.create_client(user_id, fresh=False)
                
                if client and await client.is_user_authorized():
                    logger.info(f"✅ User {user_id} reconnected from session")
                    return True
                else:
                    logger.info(f"⚠️ Session exists but not authorized")
            
            logger.info(f"🆕 Need fresh login for user {user_id}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error starting monitoring: {e}")
            return False
    
    async def cleanup(self):
        """پاکسازی تمام اتصالات"""
        try:
            logger.info(f"🧹 Cleaning up {len(self.clients)} clients...")
            
            for user_id, client in list(self.clients.items()):
                try:
                    await client.disconnect()
                    logger.debug(f"✅ Disconnected client {user_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Error disconnecting {user_id}: {e}")
            
            self.clients.clear()
            logger.info("✅ Cleanup complete")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")