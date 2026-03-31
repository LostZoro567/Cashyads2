import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from telegram.error import BadRequest

# ── Handlers ──────────────────────────────────────────────
from handlers.watch_ads_handler import (
    start, start_referral, web_app_data,
    balance, bonus, refer, spin, leaderboard,
    withdraw_menu, process_withdrawal, confirm_withdrawal,
    handle_payment_details, back_to_balance, back_methods,
    withdrawal_status, get_main_keyboard,
)
from handlers.broadcast_handler import (
    broadcast_handler, cleanup_handler,
    setstatus_handler, pending_handler,
)
from handlers.extra_handler import extra          # plain async function — NOT a handler object
from handlers.tasks_handler import (
    tasks_handler, task_callback_handler,
    handle_task_code_input,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing in .env!")


async def error_handler(update: Update, context):
    logging.error(f"Update {update} caused error: {context.error}")
    if isinstance(context.error, BadRequest):
        logging.error(f"BadRequest detail: {context.error}")


async def unknown_command(update: Update, context):
    await update.message.reply_text(
        "👇 <b>Use the buttons below!</b>",
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )


# ── Smart message router ───────────────────────────────────
# Determines what to do with plain text messages that aren't buttons or commands.
# Priority:
#   1. Awaiting task code  → handle_task_code_input
#   2. Awaiting payment details → handle_payment_details

async def smart_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_task_code'):
        await handle_task_code_input(update, context)
    elif 'withdrawal_method' in context.user_data:
        await handle_payment_details(update, context)
    else:
        await unknown_command(update, context)


# Needed for type hint in smart_text_handler
from telegram.ext import ContextTypes


async def main():
    from utils.supabase import db
    await db.init_table()
    print("✅ Cashyads v2 Ready!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    # ── COMMAND HANDLERS ──────────────────────────────────
    # /start with referral arg MUST come before generic /start
    app.add_handler(CommandHandler("start", start_referral, has_args=True))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", withdrawal_status))

    # Admin commands
    app.add_handler(broadcast_handler)
    app.add_handler(cleanup_handler)
    app.add_handler(setstatus_handler)
    app.add_handler(pending_handler)

    # ── BUTTON / MENU MESSAGE HANDLERS ───────────────────
    BUTTON_FILTER = (
        "^(Watch Ads 💰|Balance 💳|Bonus 🎁|Refer and Earn 👥"
        "|Tasks 📋|Extra ➡️|🎰 Spin|🏆 Leaderboard)$"
    )

    app.add_handler(MessageHandler(filters.Regex("^(Balance 💳)$"),         balance))
    app.add_handler(MessageHandler(filters.Regex("^(Bonus 🎁)$"),           bonus))
    app.add_handler(MessageHandler(filters.Regex("^(Refer and Earn 👥)$"),  refer))
    app.add_handler(MessageHandler(filters.Regex("^(Tasks 📋)$"),           tasks_handler))
    app.add_handler(MessageHandler(filters.Regex("^(Extra ➡️)$"),           extra))   # plain function ✅
    app.add_handler(MessageHandler(filters.Regex("^(🎰 Spin)$"),            spin))
    app.add_handler(MessageHandler(filters.Regex("^(🏆 Leaderboard)$"),     leaderboard))

    # Web app data (ad completion from Mini App)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))

    # ── CALLBACK QUERY HANDLERS ───────────────────────────
    app.add_handler(CallbackQueryHandler(withdraw_menu,        pattern="^withdraw$"))
    app.add_handler(CallbackQueryHandler(process_withdrawal,   pattern="^withdraw_"))
    app.add_handler(CallbackQueryHandler(confirm_withdrawal,   pattern="^confirm_withdraw_"))
    app.add_handler(CallbackQueryHandler(back_methods,         pattern="^back_methods$"))
    app.add_handler(CallbackQueryHandler(back_to_balance,      pattern="^back_balance$"))
    app.add_handler(CallbackQueryHandler(task_callback_handler,pattern="^task_"))

    # ── CATCH-ALL TEXT HANDLER ────────────────────────────
    # Handles: task code input, payment details, unknown text
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(BUTTON_FILTER),
        smart_text_handler
    ))

    print("🤖 Cashyads v2 LIVE!")
    print("=" * 50)
    print("✅ Coins system active (1000 coins = ₹10)")
    print("✅ Streak system active")
    print("✅ Daily spin active")
    print("✅ Weekly leaderboard active")
    print("✅ Real tasks system active")
    print("✅ Withdrawal status tracking active")
    print("✅ Admin /setstatus & /pending commands")
    print("=" * 50)

    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
