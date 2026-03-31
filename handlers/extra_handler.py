from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.supabase import db, coins_to_rs


async def extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extra info page"""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)

    if not user:
        await update.message.reply_text("❌ <b>User not found!</b>", parse_mode='HTML')
        return

    coins = int(user.get("coins", 0))
    rs = coins_to_rs(coins)
    referrals = int(user.get("referrals", 0))
    streak = int(user.get("streak", 0))
    ads = int(user.get("total_ads_watched", 0))
    total_users = await db.get_total_user_count()

    keyboard = [
        [InlineKeyboardButton("📢 Channel", url="https://t.me/CashyAds")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/CashyadsSupportBot")],
    ]

    await update.message.reply_text(
        f"➡️ <b>EXTRA INFO</b>\n\n"
        f"👤 <b>Your Stats:</b>\n"
        f"🪙 Coins: <b>{coins:,}</b> (₹{rs:.1f})\n"
        f"👥 Referrals: {referrals}\n"
        f"🔥 Streak: {streak} days\n"
        f"📺 Ads Watched: {ads}\n\n"
        f"📊 <b>Bot Stats:</b>\n"
        f"👥 Total Users: {total_users:,}\n\n"
        f"📢 <b>Official Links:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

# NOTE: This is a plain async function, NOT a MessageHandler object.
# Register it in main.py using:
#   MessageHandler(filters.Regex("^(Extra ➡️)$"), extra)
