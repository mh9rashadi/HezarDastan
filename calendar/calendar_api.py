import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json

logger = logging.getLogger(__name__)

class GoogleCalendarManager:
    def __init__(self, service_account_file: str, calendar_id: str):
        self.service_account_file = service_account_file
        self.calendar_id = calendar_id
        self.service = None
        self.initialize_service()
    
    def initialize_service(self):
        """راه‌اندازی سرویس Google Calendar"""
        try:
            if not os.path.exists(self.service_account_file):
                logger.error(f"Service account file not found: {self.service_account_file}")
                return False
            
            # بارگذاری credentials
            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
            # ایجاد سرویس
            self.service = build('calendar', 'v3', credentials=credentials)
            
            logger.info("Google Calendar service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing Google Calendar service: {e}")
            return False
    
    def create_event(self, title: str, description: str = "", 
                    start_time: datetime = None, end_time: datetime = None,
                    attendees: List[str] = None) -> Optional[Dict[str, Any]]:
        """ایجاد رویداد جدید در تقویم"""
        try:
            if not self.service:
                logger.error("Google Calendar service not initialized")
                return None
            
            # تنظیم زمان‌های پیش‌فرض
            if not start_time:
                start_time = datetime.now() + timedelta(hours=1)
            if not end_time:
                end_time = start_time + timedelta(hours=1)
            
            # ایجاد بدنه رویداد
            event_body = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tehran',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tehran',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 روز قبل
                        {'method': 'popup', 'minutes': 30},      # 30 دقیقه قبل
                    ],
                },
            }
            
            # اضافه کردن شرکت‌کنندگان
            if attendees:
                event_body['attendees'] = [{'email': email} for email in attendees]
            
            # ایجاد رویداد
            event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event_body
            ).execute()
            
            logger.info(f"Event created successfully: {event.get('id')}")
            
            return {
                'id': event.get('id'),
                'title': event.get('summary'),
                'description': event.get('description'),
                'start_time': start_time,
                'end_time': end_time,
                'html_link': event.get('htmlLink'),
                'created': event.get('created'),
                'updated': event.get('updated')
            }
            
        except HttpError as e:
            logger.error(f"HTTP error creating event: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating event: {e}")
            return None
    
    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات رویداد"""
        try:
            if not self.service:
                logger.error("Google Calendar service not initialized")
                return None
            
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            return {
                'id': event.get('id'),
                'title': event.get('summary'),
                'description': event.get('description'),
                'start_time': event.get('start', {}).get('dateTime'),
                'end_time': event.get('end', {}).get('dateTime'),
                'html_link': event.get('htmlLink'),
                'status': event.get('status'),
                'created': event.get('created'),
                'updated': event.get('updated')
            }
            
        except HttpError as e:
            logger.error(f"HTTP error getting event: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting event: {e}")
            return None
    
    def update_event(self, event_id: str, title: str = None, 
                    description: str = None, start_time: datetime = None,
                    end_time: datetime = None) -> Optional[Dict[str, Any]]:
        """به‌روزرسانی رویداد"""
        try:
            if not self.service:
                logger.error("Google Calendar service not initialized")
                return None
            
            # دریافت رویداد فعلی
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            # به‌روزرسانی فیلدها
            if title:
                event['summary'] = title
            if description:
                event['description'] = description
            if start_time:
                event['start'] = {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tehran',
                }
            if end_time:
                event['end'] = {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tehran',
                }
            
            # ذخیره تغییرات
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"Event updated successfully: {event_id}")
            
            return {
                'id': updated_event.get('id'),
                'title': updated_event.get('summary'),
                'description': updated_event.get('description'),
                'start_time': updated_event.get('start', {}).get('dateTime'),
                'end_time': updated_event.get('end', {}).get('dateTime'),
                'html_link': updated_event.get('htmlLink'),
                'updated': updated_event.get('updated')
            }
            
        except HttpError as e:
            logger.error(f"HTTP error updating event: {e}")
            return None
        except Exception as e:
            logger.error(f"Error updating event: {e}")
            return None
    
    def delete_event(self, event_id: str) -> bool:
        """حذف رویداد"""
        try:
            if not self.service:
                logger.error("Google Calendar service not initialized")
                return False
            
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            logger.info(f"Event deleted successfully: {event_id}")
            return True
            
        except HttpError as e:
            logger.error(f"HTTP error deleting event: {e}")
            return False
        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            return False
    
    def list_events(self, time_min: datetime = None, time_max: datetime = None,
                   max_results: int = 10) -> List[Dict[str, Any]]:
        """لیست رویدادها"""
        try:
            if not self.service:
                logger.error("Google Calendar service not initialized")
                return []
            
            # تنظیم زمان‌های پیش‌فرض
            if not time_min:
                time_min = datetime.now()
            if not time_max:
                time_max = time_min + timedelta(days=30)
            
            # درخواست رویدادها
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min.isoformat() + 'Z',
                timeMax=time_max.isoformat() + 'Z',
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            result = []
            for event in events:
                result.append({
                    'id': event.get('id'),
                    'title': event.get('summary'),
                    'description': event.get('description'),
                    'start_time': event.get('start', {}).get('dateTime'),
                    'end_time': event.get('end', {}).get('dateTime'),
                    'html_link': event.get('htmlLink'),
                    'status': event.get('status'),
                    'created': event.get('created'),
                    'updated': event.get('updated')
                })
            
            logger.info(f"Retrieved {len(result)} events")
            return result
            
        except HttpError as e:
            logger.error(f"HTTP error listing events: {e}")
            return []
        except Exception as e:
            logger.error(f"Error listing events: {e}")
            return []
    
    def create_meeting_from_message(self, message_text: str, user_name: str = "کاربر") -> Optional[Dict[str, Any]]:
        """ایجاد جلسه از روی متن پیام"""
        try:
            # استخراج اطلاعات از پیام
            title = f"جلسه با {user_name}"
            description = f"جلسه ایجاد شده از پیام:\n{message_text}"
            
            # تلاش برای استخراج زمان
            start_time = None
            end_time = None
            
            # الگوهای ساده برای تشخیص زمان
            import re
            
            # تشخیص ساعت (مثل 14:30 یا 2:30)
            time_match = re.search(r'(\d{1,2}):(\d{2})', message_text)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                
                # تنظیم برای امروز یا فردا
                now = datetime.now()
                start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if start_time <= now:
                    start_time += timedelta(days=1)
                
                end_time = start_time + timedelta(hours=1)
            
            # اگر زمان مشخص نشده، برای فردا ساعت 10 صبح تنظیم کن
            if not start_time:
                tomorrow = datetime.now() + timedelta(days=1)
                start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(hours=1)
            
            # ایجاد رویداد
            event = self.create_event(
                title=title,
                description=description,
                start_time=start_time,
                end_time=end_time
            )
            
            return event
            
        except Exception as e:
            logger.error(f"Error creating meeting from message: {e}")
            return None
    
    def test_connection(self) -> bool:
        """تست اتصال به Google Calendar"""
        try:
            if not self.service:
                return False
            
            # تلاش برای دریافت لیست تقویم‌ها
            calendar_list = self.service.calendarList().list().execute()
            
            logger.info("Google Calendar connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Google Calendar connection test failed: {e}")
            return False

# تابع اصلی برای تست
def main():
    """تابع اصلی برای تست Google Calendar"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv('config.env')
    
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID")
    
    if not service_account_file or not calendar_id:
        logger.error("Missing Google Calendar configuration!")
        return
    
    # ایجاد manager
    calendar_manager = GoogleCalendarManager(service_account_file, calendar_id)
    
    # تست اتصال
    if calendar_manager.test_connection():
        print("✅ Google Calendar connection successful!")
        
        # تست ایجاد رویداد
        test_event = calendar_manager.create_event(
            title="تست جلسه",
            description="این یک جلسه تست است",
            start_time=datetime.now() + timedelta(hours=1),
            end_time=datetime.now() + timedelta(hours=2)
        )
        
        if test_event:
            print(f"✅ Test event created: {test_event['html_link']}")
        else:
            print("❌ Failed to create test event")
    else:
        print("❌ Google Calendar connection failed!")

if __name__ == "__main__":
    main()
