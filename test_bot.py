import asyncio
import sys
sys.path.insert(0, '.')

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import CommandStart
from app.config import get_settings
from app.bot.handlers.start import start_router

async def test_start_handler():
    """Test that the start handler works correctly"""
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    
    # Include our start router
    dp.include_router(start_router)
    
    # Create a mock message object
    class MockMessage:
        def __init__(self):
            self.text = "/start"
            self.bot = bot
            self.from_user = type('obj', (object,), {'id': 12345, 'first_name': 'Test'})()
            self.chat = type('obj', (object,), {'id': 12345, 'type': 'private'})()
            self.answer_called = False
            self.answer_text = ""
            self.answer_reply_markup = None
            
        async def answer(self, text, reply_markup=None):
            self.answer_called = True
            self.answer_text = text
            self.answer_reply_markup = reply_markup
            print(f"Bot would respond with: {text}")
            if reply_markup:
                print(f"With keyboard: {reply_markup}")
    
    # Create mock message
    mock_msg = MockMessage()
    
    # Find the start handler
    start_handler = None
    for handler in dp.message.handlers:
        print(f"Handler: {handler}")
        # Check if this is our start command handler
        if hasattr(handler, 'callback') and handler.callback.__name__ == 'start_command':
            start_handler = handler
            break
    
    if start_handler:
        print("Found start command handler")
        # Try to call it
        try:
            await start_handler.callback(mock_msg)
            print("Start handler executed successfully")
            if mock_msg.answer_called:
                print("Handler sent a response as expected")
            else:
                print("Handler did not send a response")
        except Exception as e:
            print(f"Error executing start handler: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Could not find start command handler in dispatcher")
        
        # Let's check what handlers we have
        print("Available message handlers:")
        for i, handler in enumerate(dp.message.handlers):
            print(f"  {i}: {handler}")
            if hasattr(handler, 'callback'):
                print(f"      Callback: {handler.callback}")

if __name__ == "__main__":
    asyncio.run(test_start_handler())