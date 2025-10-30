from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import logging
import asyncio
from typing import Optional

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.db import DatabaseManager
from telethon_client.manager import TelethonManager

# تنظیمات لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# کلاس‌های حالت برای FSM
class UserStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
    waiting_for_confirmation = State()

class TelegramBot:
    def __init__(self, bot_token: str, api_id: int, api_hash: str):
        self.bot = Bot(token=bot_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.db = DatabaseManager()
        self.api_id = api_id
        self.api_hash = api_hash
        # Telethon manager
        self.telethon_manager = TelethonManager(api_id, api_hash)
        
        # ثبت handlerها
        self.register_handlers()
    
    def register_handlers(self):
        """ثبت تمام handlerهای ربات"""
        self.dp.message.register(self.start_command, CommandStart())
        self.dp.message.register(self.connect_telegram_command, Command("connect"))
        self.dp.message.register(self.status_command, Command("status"))
        self.dp.message.register(self.help_command, Command("help"))
        self.dp.message.register(self.handle_phone_number, UserStates.waiting_for_phone)
        self.dp.message.register(self.handle_verification_code, UserStates.waiting_for_code)
        self.dp.message.register(self.handle_2fa_password, UserStates.waiting_for_password)
        self.dp.message.register(self.handle_confirmation, UserStates.waiting_for_confirmation)
        self.dp.callback_query.register(self.handle_callback_query)
    
    async def start_command(self, message: types.Message):
        """Handler برای دستور /start"""
        try:
            user = message.from_user
            
            # ذخیره اطلاعات کاربر در دیتابیس
            self.db.add_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            welcome_text = f"""
🤖 **خوش آمدید {user.first_name}!**

من یک دستیار هوشمند برای تنظیم خودکار جلسات هستم. 

**چگونه کار می‌کنم؟**
• شما با من شماره تلفن خود را به اشتراک می‌گذارید
• من به حساب تلگرام شما متصل می‌شوم
• پیام‌های شما را مانیتور می‌کنم
• وقتی کلماتی مثل "جلسه"، "قرار" یا "meeting" ببینم، به شما اطلاع می‌دهم
• شما تایید می‌کنید و من جلسه را در تقویم شما ثبت می‌کنم

**برای شروع روی دکمه زیر کلیک کنید:**
            """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 اتصال حساب تلگرام", callback_data="connect_telegram")]
            ])
            
            await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error in start_command: {e}")
            await message.answer("❌ خطا در پردازش درخواست. لطفاً دوباره تلاش کنید.")
    
    async def connect_telegram_command(self, message: types.Message, state: FSMContext):
        """Handler برای دستور /connect"""
        await self.start_telegram_connection(message, state)
    
    async def start_telegram_connection(self, message: types.Message, state: FSMContext = None):
        """شروع فرآیند اتصال به تلگرام"""
        user_id = message.from_user.id
        
        # بررسی اینکه آیا کاربر قبلاً متصل شده یا نه
        user_data = self.db.get_user(user_id)
        if user_data and user_data.get('is_telethon_connected'):
            await message.answer("✅ شما قبلاً به حساب تلگرام خود متصل شده‌اید!")
            return
        
        # درخواست شماره تلفن
        phone_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 ارسال شماره تلفن", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            "📱 لطفاً شماره تلفن خود را ارسال کنید تا بتوانم به حساب تلگرام شما متصل شوم:",
            reply_markup=phone_keyboard
        )
        
        await message.answer(
            "⚠️ **نکته مهم:**\n"
            "شماره تلفن شما باید همان شماره‌ای باشد که در تلگرام استفاده می‌کنید.",
            parse_mode="Markdown"
        )
        
        # تغییر حالت کاربر
        await message.answer("حالا روی دکمه 'ارسال شماره تلفن' کلیک کنید.")
        
        # تغییر حالت به انتظار شماره تلفن
        await message.answer("لطفاً شماره تلفن خود را ارسال کنید:", reply_markup=phone_keyboard)
        
        # تغییر حالت کاربر
        await state.set_state(UserStates.waiting_for_phone)
    
    async def handle_phone_number(self, message: types.Message, state: FSMContext):
        """پردازش شماره تلفن دریافتی"""
        if message.contact:
            phone_number = message.contact.phone_number
            user_id = message.from_user.id
            
            # ذخیره شماره تلفن در دیتابیس
            self.db.add_user(
                telegram_id=user_id,
                phone_number=phone_number,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            
            await message.answer(
                f"✅ شماره تلفن شما ({phone_number}) دریافت شد!\n\n"
                "🔐 حالا در حال اتصال به حساب تلگرام شما هستم...\n"
                "لطفاً کد تأیید که به تلگرام شما ارسال می‌شود را وارد کنید:",
                reply_markup=types.ReplyKeyboardRemove()
            )
            
            # ذخیره شماره در حافظه حالت
            await state.update_data(phone_number=phone_number)
            
            # ارسال کد ورود از طریق Telethon
            ok = await self.start_telethon_connection(user_id, phone_number)
            if ok:
                # تغییر حالت به انتظار کد تأیید
                await state.set_state(UserStates.waiting_for_code)
            else:
                await message.answer("❌ ارسال کد ورود با خطا مواجه شد. کمی بعد دوباره تلاش کنید.")
            
        else:
            await message.answer(
                "❌ لطفاً شماره تلفن خود را از طریق دکمه 'ارسال شماره تلفن' ارسال کنید."
            )
    
    async def start_telethon_connection(self, user_id: int, phone_number: str) -> bool:
        """شروع ارسال کد ورود با Telethon"""
        try:
            logger.info(f"Starting Telethon code request for user {user_id} with phone {phone_number}")
            if not self.telethon_manager:
                logger.error("Telethon manager is not initialized")
                return False
            sent = await self.telethon_manager.send_login_code(user_id, phone_number)
            return sent
        except Exception as e:
            logger.error(f"Error starting Telethon connection: {e}")
            return False
    
    async def handle_verification_code(self, message: types.Message, state: FSMContext):
        """پردازش کد تأیید"""
        code = message.text.strip()
        user_id = message.from_user.id
        
        if not code.isdigit() or len(code) not in (5, 6):
            await message.answer("❌ کد تأیید باید ۵ یا ۶ رقم باشد. لطفاً دوباره وارد کنید:")
            return
        
        try:
            logger.info(f"Verification code received for user {user_id}: {code}")
            data = await state.get_data()
            phone = data.get("phone_number")
            if not phone:
                await message.answer("❌ شماره تلفن پیدا نشد. لطفاً دوباره /connect را بزنید.")
                await state.clear()
                return

            result = await self.telethon_manager.confirm_login_code(user_id, code)
            if result.get('need_password'):
                await message.answer("🔒 احراز هویت دو مرحله‌ای (2FA) فعال است. لطفاً گذرواژه 2FA حساب تلگرام خود را ارسال کنید.")
                await state.set_state(UserStates.waiting_for_password)
                return
            if result.get('error') == 'code_expired':
                # try auto resend latest code (fallback to SMS if needed)
                await message.answer("⌛ کد منقضی شد؛ در حال ارسال کد جدید هستم...")
                # تلاش برای ارسال دوباره کد
                data = await state.get_data()
                phone = data.get("phone_number")
                if phone:
                    await self.telethon_manager.send_login_code(user_id, phone)
                    await message.answer("📩 کد جدید ارسال شد. لطفاً آخرین کد را وارد کنید.")
                else:
                    await message.answer("لطفاً دوباره /connect را بزنید.")
                return
            if result.get('ok'):
                await message.answer(
                    "✅ کد تأیید صحیح است!\n"
                    "🔗 اتصال به حساب تلگرام شما با موفقیت برقرار شد.\n\n"
                    "📱 حالا من پیام‌های شما را مانیتور می‌کنم و هر زمان کلماتی مثل 'جلسه'، 'قرار' یا 'meeting' ببینم، به شما اطلاع می‌دهم."
                )
                await state.clear()
            else:
                await message.answer("❌ کد نامعتبر است. لطفاً دوباره تلاش کنید یا /connect را بزنید.")
            
        except Exception as e:
            logger.error(f"Error verifying code: {e}")
            await message.answer("❌ خطا در تأیید کد. لطفاً دوباره تلاش کنید.")
    
    async def handle_confirmation(self, message: types.Message, state: FSMContext):
        """پردازش تایید کاربر برای ثبت جلسه"""
        user_id = message.from_user.id
        text = message.text.lower()
        
        if "بله" in text or "yes" in text or "تایید" in text:
            await message.answer("✅ جلسه شما در تقویم ثبت شد!")
            # TODO: ثبت جلسه در Google Calendar
        elif "خیر" in text or "no" in text or "نه" in text:
            await message.answer("❌ جلسه ثبت نشد.")
        else:
            await message.answer("لطفاً 'بله' یا 'خیر' پاسخ دهید.")
        
        await state.clear()

    async def handle_2fa_password(self, message: types.Message, state: FSMContext):
        """دریافت گذرواژه 2FA و تکمیل ورود"""
        try:
            user_id = message.from_user.id
            password = message.text.strip()
            result = await self.telethon_manager.confirm_login_code(user_id, code=None, password=password)
            if result.get('ok'):
                await message.answer("✅ ورود با گذرواژه 2FA انجام شد و اتصال برقرار است.")
                await state.clear()
            else:
                await message.answer("❌ گذرواژه 2FA نادرست بود. دوباره تلاش کنید یا /connect را بزنید.")
        except Exception as e:
            logger.error(f"Error handling 2FA password: {e}")
            await message.answer("❌ خطا در تایید گذرواژه 2FA.")
    
    async def handle_callback_query(self, callback_query: types.CallbackQuery, state: FSMContext):
        """پردازش callback queryها"""
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        if data == "connect_telegram":
            await self.start_telegram_connection(callback_query.message, state)
        
        await callback_query.answer()
    
    async def status_command(self, message: types.Message):
        """نمایش وضعیت کاربر"""
        user_id = message.from_user.id
        user_data = self.db.get_user(user_id)
        
        if not user_data:
            await message.answer("❌ شما هنوز ثبت‌نام نکرده‌اید. از /start استفاده کنید.")
            return
        
        status_text = f"""
📊 **وضعیت حساب شما:**

👤 نام: {user_data.get('first_name', 'نامشخص')}
📱 شماره: {user_data.get('phone_number', 'ثبت نشده')}
🔗 اتصال تلگرام: {'✅ متصل' if user_data.get('is_telethon_connected') else '❌ قطع'}
📅 اتصال تقویم: {'✅ متصل' if user_data.get('calendar_connected') else '❌ قطع'}
📅 تاریخ عضویت: {user_data.get('created_at', 'نامشخص')}
        """
        
        await message.answer(status_text, parse_mode="Markdown")
    
    async def help_command(self, message: types.Message):
        """راهنمای استفاده"""
        help_text = """
📖 **راهنمای استفاده:**

**دستورات موجود:**
/start - شروع و ثبت‌نام
/connect - اتصال به حساب تلگرام
/status - نمایش وضعیت حساب
/help - این راهنما

**نحوه کار:**
1️⃣ ابتدا با /start شروع کنید
2️⃣ شماره تلفن خود را ارسال کنید
3️⃣ کد تأیید را وارد کنید
4️⃣ حالا من پیام‌های شما را مانیتور می‌کنم

**کلمات کلیدی که شناسایی می‌کنم:**
• جلسه
• قرار
• meeting
• appointment
• session

**پشتیبانی:**
اگر مشکلی داشتید، با پشتیبانی تماس بگیرید.
        """
        
        await message.answer(help_text, parse_mode="Markdown")
    
    async def send_meeting_detection_message(self, user_id: int, message_text: str, chat_id: int):
        """ارسال پیام تشخیص جلسه به کاربر"""
        detection_text = f"""
🔍 **پیام مرتبط با جلسه شناسایی شد!**

📝 متن پیام:
{message_text}

❓ آیا مایلید جلسه‌ای در تقویم شما ثبت کنم؟

برای تایید 'بله' و برای رد 'خیر' بنویسید.
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ بله، ثبت کن", callback_data=f"confirm_meeting_{chat_id}")],
            [InlineKeyboardButton(text="❌ خیر", callback_data=f"reject_meeting_{chat_id}")]
        ])
        
        await self.bot.send_message(user_id, detection_text, reply_markup=keyboard, parse_mode="Markdown")
    
    async def start_polling(self):
        """شروع polling ربات"""
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)

# تابع اصلی برای اجرای ربات
async def main():
    """تابع اصلی برای اجرای ربات"""
    import os
    from dotenv import load_dotenv
    
    # بارگذاری متغیرهای محیطی
    load_dotenv('config.env')
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_id = int(os.getenv("TELEGRAM_API_ID"))
    api_hash = os.getenv("TELEGRAM_API_HASH")
    
    if not all([bot_token, api_id, api_hash]):
        logger.error("Missing required environment variables!")
        return
    
    # ایجاد و اجرای ربات
    bot = TelegramBot(bot_token, api_id, api_hash)
    await bot.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
