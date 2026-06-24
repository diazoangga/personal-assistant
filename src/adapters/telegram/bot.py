"""Telegram bot handler using aiogram v3."""

import logging
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from ...core.commands import Ask
from ...main_engine import PersonalAssistantEngine

logger = logging.getLogger(__name__)


class BrainstormStates(StatesGroup):
    """FSM states for brainstorming session."""

    active = State()


class TelegramBotHandler:
    """Telegram bot using aiogram v3 for long-polling."""

    def __init__(self, bot_token: str, engine: PersonalAssistantEngine, mini_app_url: str):
        """
        Args:
            bot_token: Telegram bot token
            engine: PersonalAssistantEngine instance
            mini_app_url: HTTPS URL to the Mini App (e.g., https://ngrok-url.ngrok.io)
        """
        self.bot = Bot(token=bot_token, parse_mode=ParseMode.MARKDOWN)
        self.engine = engine
        self.mini_app_url = mini_app_url

        # FSM storage
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)

        # Router
        self.router = Router()
        self._register_handlers()
        self.dp.include_router(self.router)

    def _register_handlers(self) -> None:
        """Register message and command handlers."""

        @self.router.message(Command("start"))
        async def cmd_start(message: Message) -> None:
            """Handle /start command - show main menu."""
            await self._send_main_menu(message.chat.id, message.from_user.first_name or "User")

        @self.router.message(Command("ask"))
        async def cmd_ask(message: Message) -> None:
            """Handle /ask command - quick Q&A via bot."""
            args = message.text.replace("/ask", "").strip()
            if not args:
                await message.reply("Usage: /ask <your question>")
                return

            # Submit Ask command
            user_id = f"telegram:{message.from_user.id}"
            cmd = Ask(user=user_id, query=args)
            job_id = await self.engine.submit(cmd)

            # Send a "thinking" message
            status_msg = await message.reply("🔍 Searching your knowledge base...")

            # Stream events and update the message
            result_text = ""
            async for event in self.engine.bus.subscribe(job_id):
                from ...core.events import Message as MessageEvent
                from ...core.events import Progress, Result

                if isinstance(event, Progress):
                    await status_msg.edit_text(f"⟳ {event.phase}...\n{event.message}")
                elif isinstance(event, MessageEvent):
                    result_text += f"{event.text}\n"
                elif isinstance(event, Result):
                    if event.ok:
                        await status_msg.edit_text(f"💬 Answer:\n\n{result_text[:4096]}")
                    else:
                        await status_msg.edit_text(
                            f"❌ Error: {event.payload.get('error', 'Unknown error')}"
                        )
                    break

        @self.router.message(Command("interests"))
        async def cmd_interests(message: Message) -> None:
            """Handle /interests command - show current interests."""
            interests = await self.engine.get_interests(min_strength=0.3)

            if not interests:
                await message.reply("No tracked interests yet. Ingest some activity!")
                return

            text = "📊 Your Interests:\n\n"
            for interest in interests[:10]:
                strength_bar = "█" * int(interest.get("strength", 0) * 10)
                text += f"{interest.get('label', 'Unknown'):20} {strength_bar} ({interest.get('strength', 0):.2f})\n"

            await message.reply(text)

        @self.router.message(Command("open_app"))
        async def cmd_open_app(message: Message) -> None:
            """Handle /open_app command - launch the Mini App."""
            await self._send_main_menu(message.chat.id, message.from_user.first_name or "User")

        @self.router.message()
        async def handle_message(message: Message) -> None:
            """Handle general messages (fallback)."""
            await message.reply(
                "👋 Hi! Use the buttons below to get started, or /ask <question> for quick answers.",
                reply_markup=self._get_main_menu_keyboard(),
            )

    async def _send_main_menu(self, chat_id: int, user_name: str) -> None:
        """Send the main menu with keyboard."""
        text = f"👋 Welcome, {user_name}!\n\n"
        text += "Choose an action or open the Mini App for a richer experience:"

        keyboard = self._get_main_menu_keyboard()
        await self.bot.send_message(chat_id, text, reply_markup=keyboard)

    def _get_main_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Build the main menu inline keyboard."""
        buttons = [
            [
                InlineKeyboardButton(
                    text="🚀 Open Mini App",
                    web_app=WebAppInfo(url=self.mini_app_url),
                )
            ],
            [
                InlineKeyboardButton(text="❓ /ask <question>", callback_data="ask_help"),
                InlineKeyboardButton(text="📊 /interests", callback_data="interests_help"),
            ],
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def start_polling(self) -> None:
        """Start the bot in long-polling mode."""
        logger.info("Starting Telegram bot (long-polling)...")
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Error in bot polling: {e}")
            raise

    async def stop(self) -> None:
        """Stop the bot."""
        await self.bot.session.close()
