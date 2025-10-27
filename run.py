#!/usr/bin/env python3
"""
Production runner for Smart Meeting Assistant
"""

import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

# Add project paths
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'calendar'))

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

async def main():
    """Main function for production"""
    try:
        from bot.main import TelegramBot
        
        # Get configuration from environment variables
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        api_id = int(os.getenv("TELEGRAM_API_ID"))
        api_hash = os.getenv("TELEGRAM_API_HASH")
        
        if not all([bot_token, api_id, api_hash]):
            logger.error("Missing required environment variables!")
            logger.error("Please set: TELEGRAM_BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH")
            return
        
        logger.info("Starting Smart Meeting Assistant...")
        logger.info(f"Bot token: {bot_token[:10]}...")
        logger.info(f"API ID: {api_id}")
        
        # Create and start bot
        bot = TelegramBot(bot_token, api_id, api_hash)
        await bot.start_polling()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    print("🤖 Smart Meeting Assistant - Production Mode")
    print("=" * 50)
    asyncio.run(main())
