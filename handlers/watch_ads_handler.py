from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
)
from telegram.ext import ContextTypes
from utils.supabase import db, coins_to_rs, MIN_WITHDRAW_COINS, MIN_REFERRALS, _week_start
import os
from datetime import date
import json


def get_main_keyboard(user_id=None):
    mini_app_url = os.getenv("MINI_APP_URL", "https://teleadviewer.pages.dev/")
    
    # BULLETPROOF METHOD: Inject user_id directly into the URL
    if user_id and mini_app_url:
        # Clean the URL and add the parameter securely
        base_url = mini_app_url.rstrip('/')
        mini_app_url = f"{base_url}/?uid={user_id}"

    keyboard = []

    if mini_app_url:
        try:
            keyboard.append([KeyboardButton("Watch Ads 💰", web_app=WebAppInfo(url=mini_app_url))])
        except Exception as e:
            print(f"⚠️ WebApp button error: {e}")
            keyboard.append([KeyboardButton("Watch Ads 💰")])
    else:
        keyboard.append([KeyboardButton("Watch Ads 💰")])

    keyboard.append([KeyboardButton("Balance 💳"),     KeyboardButton("Bonus 🎁")])
    keyboard.append([KeyboardButton("Refer and Earn 👥"), KeyboardButton("Tasks 📋")])
    keyboard.append([KeyboardButton("🎰 Spin"),        KeyboardButton("🏆 Leaderboard")])
    keyboard.append([KeyboardButton("Extra ➡️")])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"User{user_id}"
    await db.create_user_if_not_exists(user_id, username)

    await update.message.reply_text(
        "<b>👋 Welcome to Cashyads!</b>\n\n"
        "💰 <b>Watch Ads</b> — earn 300–500 coins each\n"
        "👥 <b>Refer friends</b> — earn 4,000 coins + 5% commission\n"
        "🎁 <b>Daily Bonus</b> — 500 coins (2× at 7-day streak, 3× at 30-day!)\n"
        "🎰 <b>Daily Spin</b> — win up to 5,000 coins free\n"
        "📋 <b>Tasks</b> — earn 2,500 coins per task\n"
        "🏆 <b>Leaderboard</b> — compete weekly!\n\n"
        "🪙 <b>1,000 coins = ₹10</b>\n"
        "💸 Min withdrawal: <b>38,000 coins = ₹380</b>\n\n"
        "<i>Start earning now! 🚀</i>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )


async def start_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"User{user_id}"

    await db.create_user_if_not_exists(user_id, username)

    if context.args:
        referrer_code = context.args[0]
        already = await db.user_already_referred(user_id)
        if not already:
            if await db.process_referral(user_id, referrer_code):
                try:
                    referrer = await db.get_referrer_by_code(referrer_code)
                    if referrer:
                        await context.bot.send_message(
                            referrer["user_id"],
                            f"<b>🎉 Referral Bonus!</b>\n\n"
                            f"👤 <b>{username}</b> joined via your link!\n"
                            f"🪙 <b>+4,000 coins</b> added to your balance!",
                            parse_mode='HTML'
                        )
                except Exception as e:
                    print(f"⚠️ Referral notify error: {e}")

    await update.message.reply_text(
        "<b>👋 Welcome to Cashyads!</b>\n\n"
        "💰 <b>Watch Ads</b> — earn 300–500 coins each\n"
        "👥 <b>Refer friends</b> — earn 4,000 coins + 5% commission\n"
        "🎁 <b>Daily Bonus</b> — 500 coins (streaks give 2×/3× multiplier!)\n"
        "🎰 <b>Daily Spin</b> — win up to 5,000 coins free\n"
        "📋 <b>Tasks</b> — earn 2,500 coins per task\n\n"
        "🪙 <b>1,000 coins = ₹10</b>\n\n"
        "<i>Start earning now! 🚀</i>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )


# ============================================================
# AD WATCH
# ============================================================

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw = update.effective_message.web_app_data.data

    try:
        data = json.loads(raw)
    except:
        data = {}

    if data.get("ad_completed"):
        result = await db.reward_ad_watch(user_id)
        
        # Handle the NO ENERGY scenario
        if not result.get("success"):
            if result.get("reason") == "no_energy":
                mins = int(result["next_recharge_seconds"] // 60)
                secs = int(result["next_recharge_seconds"] % 60)
                await update.message.reply_text(
                    f"<b>🔋 Out of Energy!</b>\n\n"
                    f"You have 0/5 ⚡.\n"
                    f"Please wait <b>{mins}m {secs}s</b> for your next energy point before watching more ads.",
                    reply_markup=get_main_keyboard(user_id),
                    parse_mode='HTML'
                )
            return

        coins = result["coins"]
        total = result["total_coins"]
        ads = result["ads_watched"]
        milestone = result.get("milestone")
        energy_left = result["energy_left"]

        # Format the recharge timer
        mins = int(result["next_recharge_seconds"] // 60)
        secs = int(result["next_recharge_seconds"] % 60)
        timer_text = f" (Next in {mins}m {secs}s)" if energy_left < 5 else " (MAX)"

        text = (
            f"<b>✅ Ad watched!</b>\n\n"
            f"🪙 <b>+{coins} coins</b>\n"
            f"💳 Total: <b>{total:,} coins</b>\n"
            f"⚡ Energy: <b>{energy_left}/5</b>{timer_text}\n"
            f"📺 Ads watched today: {ads}"
        )

        if milestone:
            text += (
                f"\n\n<b>🎖️ MILESTONE BONUS!</b>\n"
                f"🎉 {milestone['ads']} ads watched!\n"
                f"🪙 <b>+{milestone['bonus_coins']:,} bonus coins!</b>"
            )

        await update.message.reply_text(text, reply_markup=get_main_keyboard(user_id), parse_mode='HTML')
    else:
        await update.message.reply_text(
            "❌ <b>Ad cancelled!</b>\n\nTry again 🔄",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )


# ============================================================
# BALANCE
# ============================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Refresh energy before showing balance
    energy_data = await db.get_and_update_energy(user_id)
    user = await db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ User not found!", reply_markup=get_main_keyboard(user_id), parse_mode='HTML')
        return

    coins = int(user.get("coins", 0))
    rs = coins_to_rs(coins)
    ads = int(user.get("total_ads_watched", 0))
    streak = int(user.get("streak", 0))
    referrals = int(user.get("referrals", 0))
    energy = energy_data["energy"]

    # Format Energy Timer
    if energy < 5:
        mins = int(energy_data["next_recharge_seconds"] // 60)
        secs = int(energy_data["next_recharge_seconds"] % 60)
        energy_text = f"⚡ <b>{energy}/5</b> (Next in {mins}m {secs}s)"
    else:
        energy_text = f"⚡ <b>5/5</b> (MAX)"

    progress_pct = min(int((coins / 38000) * 100), 100) # Replaced MIN_WITHDRAW_COINS for static visual
    filled = progress_pct // 10
    bar = "█" * filled + "░" * (10 - filled)

    history = await db.get_user_withdrawals(user_id)
    history_text = ""
    if history:
        history_text = "\n\n<b>📜 Recent Withdrawals:</b>\n"
        status_emoji = {"pending": "⏳", "processing": "🔄", "paid": "✅", "rejected": "❌"}
        for w in history[:3]:
            emoji = status_emoji.get(w["status"], "❓")
            history_text += f"{emoji} ₹{w['rs_amount']:.1f} via {w['method']} — <i>{w['status']}</i>\n"

    keyboard = [[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]]

    await update.message.reply_text(
        f"<b>💳 Your Balance</b>\n\n"
        f"🪙 <b>{coins:,} coins</b>\n"
        f"💵 ≈ <b>₹{rs:.1f}</b>\n"
        f"{energy_text}\n\n"
        f"<b>📊 Stats:</b>\n"
        f"📺 Ads watched: {ads}\n"
        f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}\n"
        f"👥 Referrals: {referrals}\n\n"
        f"<b>Progress to withdrawal:</b>\n"
        f"[{bar}] {progress_pct}%\n"
        f"<i>{coins:,}/38,000 coins</i>"
        f"{history_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


# ============================================================
# DAILY BONUS
# ============================================================

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    result = await db.give_daily_bonus(user_id)

    if result.get("success"):
        coins = result["coins"]
        streak = result["streak"]
        multiplier = result["multiplier"]

        streak_text = ""
        if streak >= 30:
            streak_text = "🔥 <b>30-DAY STREAK! 3× multiplier!</b>"
        elif streak >= 7:
            streak_text = "🔥 <b>7-DAY STREAK! 2× multiplier!</b>"
        elif streak >= 3:
            streak_text = f"🔥 Streak: <b>{streak} days</b> — keep going for bonus multiplier!"
        else:
            streak_text = f"🔥 Streak: <b>{streak} day</b>"

        await update.message.reply_text(
            f"<b>🎁 Daily Bonus Claimed!</b>\n\n"
            f"🪙 <b>+{coins} coins</b>"
            + (f" ({multiplier}× streak bonus!)" if multiplier > 1 else "") +
            f"\n\n{streak_text}\n\n"
            f"💡 <b>Streak rewards:</b>\n"
            f"7 days = 2× bonus (1,000 coins)\n"
            f"30 days = 3× bonus (1,500 coins)\n\n"
            f"Come back tomorrow! 📅",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
    elif result.get("already_claimed"):
        streak = result.get("streak", 0)
        await update.message.reply_text(
            f"<b>⏳ Already Claimed!</b>\n\n"
            f"🔥 Current streak: <b>{streak} days</b>\n\n"
            f"Come back tomorrow for your next bonus! 📅",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ Error claiming bonus. Please try again!",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )


# ============================================================
# REFER
# ============================================================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)

    if not user:
        await update.message.reply_text("❌ User not found!", reply_markup=get_main_keyboard(user_id), parse_mode='HTML')
        return

    referral_code = user.get("referral_code", "")
    referrals = int(user.get("referrals", 0))
    bot_username = os.getenv("BOT_USERNAME", "Cashyadsbot")
    link = f"https://t.me/{bot_username}?start={referral_code}"
    share_url = f"https://t.me/share/url?url={link}&text=Join%20Cashyads%20and%20earn%20money%20watching%20ads%20%F0%9F%92%B0"

    # Referral milestones display
    next_milestone = None
    for m in [5, 10, 25, 50]:
        if referrals < m:
            next_milestone = m
            break

    milestone_text = ""
    if next_milestone:
        bonuses = {5: "2,000", 10: "4,000", 25: "10,000", 50: "25,000"}
        milestone_text = (
            f"\n🎯 <b>Next milestone:</b> {next_milestone} referrals → "
            f"+{bonuses[next_milestone]} bonus coins!"
        )

    keyboard = [[InlineKeyboardButton("📲 Share Link", url=share_url)]]

    await update.message.reply_text(
        f"<b>👥 Refer & Earn</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"👥 Your referrals: <b>{referrals}</b>{milestone_text}\n\n"
        f"<b>💰 Rewards per referral:</b>\n"
        f"🪙 <b>4,000 coins</b> when they join\n"
        f"🪙 <b>5% commission</b> on all their ad earnings\n\n"
        f"👇 Share your link!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


# ============================================================
# SPIN WHEEL
# ============================================================

async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    result = await db.do_spin(user_id)

    if not result["success"]:
        await update.message.reply_text(
            "<b>🎰 Daily Spin</b>\n\n"
            "⏳ You've already spun today!\n\n"
            "Come back tomorrow for another free spin! 📅",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
        return

    prize = result["prize"]
    total = result["total_coins"]

    if prize["coins"] == 0:
        result_text = "💀 <b>Better luck tomorrow!</b>\n0 coins this time."
    elif prize["coins"] >= 5000:
        result_text = f"🎰 <b>JACKPOT!!</b> You won {prize['label']}!"
    elif prize["coins"] >= 2500:
        result_text = f"💎 <b>Big win!</b> You won {prize['label']}!"
    else:
        result_text = f"🎉 You won <b>{prize['label']}</b>!"

    await update.message.reply_text(
        f"<b>🎰 Daily Spin Result!</b>\n\n"
        f"{'🎡 ' * 3}\n\n"
        f"{result_text}\n\n"
        f"🪙 <b>+{prize['coins']} coins</b>\n"
        f"💳 Total: <b>{total:,} coins</b>\n\n"
        f"<i>Spin again tomorrow!</i>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )


# ============================================================
# LEADERBOARD
# ============================================================

# Drop-in replacement for the leaderboard() function in watch_ads_handler.py
# Replace the entire leaderboard() function with this one.

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Both queries run; user row likely cached already so get_user is free
    top  = await db.get_weekly_leaderboard(10)
    user = await db.get_user(user_id)

    ws          = _week_start()
    user_weekly = 0
    rank        = 0

    if user:
        user_weekly = int(user.get("weekly_coins", 0)) if user.get("weekly_reset_date") == ws else 0

    # Count rank from leaderboard list first (free, no extra DB call)
    # Only fall back to DB rank if user isn't in top 10
    user_in_top = False
    medals      = ["🥇", "🥈", "🥉"]
    board_lines = []

    for i, entry in enumerate(top):
        medal  = medals[i] if i < 3 else f"{i+1}."
        uid    = entry.get("user_id")
        uname  = entry.get("username") or f"User{uid}"
        coins  = int(entry.get("weekly_coins", 0))
        marker = " ← <b>you</b>" if uid == user_id else ""
        if uid == user_id:
            user_in_top = True
            rank = i + 1
        board_lines.append(f"{medal} @{uname} — <b>{coins:,}</b>{marker}")

    if not user_in_top:
        rank = await db.get_user_rank(user_id)

    board_text = "\n".join(board_lines) if board_lines else "<i>No entries yet this week!</i>"

    await update.message.reply_text(
        f"<b>🏆 Weekly Leaderboard</b>\n"
        f"<i>Resets every Monday</i>\n\n"
        f"{board_text}\n\n"
        f"<b>Your position:</b> #{rank}\n"
        f"🪙 Your weekly coins: <b>{user_weekly:,}</b>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )


# ============================================================
# WITHDRAWAL FLOW
# ============================================================

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Paytm",          callback_data="withdraw_paytm")],
        [InlineKeyboardButton("📱 UPI",             callback_data="withdraw_upi")],
        [InlineKeyboardButton("🏦 Bank Transfer",   callback_data="withdraw_bank")],
        [InlineKeyboardButton("💵 PayPal",          callback_data="withdraw_paypal")],
        [InlineKeyboardButton("₿ USDT (TRC20)",     callback_data="withdraw_usdt")],
        [InlineKeyboardButton("⬅️ Back",            callback_data="back_balance")],
    ]
    await query.edit_message_text(
        "<b>💳 Choose Payment Method</b>\n\n"
        "<i>Select your preferred withdrawal method:</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # FIX: query.data is e.g. "withdraw_upi" — split correctly
    method = query.data.split("_", 1)[1].upper()  # "withdraw_upi" → "UPI"

    check = await db.can_withdraw(user_id)

    if check["can"]:
        coins = check["coins"]
        rs = check["rs"]
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw_{method}")],
            [InlineKeyboardButton("⬅️ Back",   callback_data="back_methods")],
        ]
        await query.edit_message_text(
            f"<b>💸 Withdrawal Ready!</b>\n\n"
            f"🪙 <b>{coins:,} coins</b>\n"
            f"💵 ≈ <b>₹{rs:.1f}</b>\n"
            f"📌 Method: <b>{method}</b>\n"
            f"👥 Referrals: {check['referrals']}\n\n"
            f"✅ All requirements met!\n"
            f"Click confirm to proceed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_methods")]]
        await query.edit_message_text(
            f"<b>❌ Cannot Withdraw Yet</b>\n\n"
            f"<b>Reason:</b> {check['reason']}\n\n"
            f"<b>Requirements:</b>\n"
            f"🪙 Min coins: <b>{MIN_WITHDRAW_COINS:,}</b> (= ₹380)\n"
            f"👥 Min referrals: <b>{MIN_REFERRALS}</b>\n\n"
            f"<i>Keep earning to unlock!</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )


async def confirm_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # FIX: query.data = "confirm_withdraw_UPI" → split on "_", take last part
    parts = query.data.split("_")
    method = parts[-1].upper()

    coins = await db.get_coins(user_id)
    rs = coins_to_rs(coins)

    context.user_data['withdrawal_method'] = method
    context.user_data['withdrawal_coins'] = coins

    prompts = {
        "PAYTM":  (
            f"<b>📱 Enter Your Paytm Number</b>\n\n"
            f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n\n"
            f"Reply with your 10-digit number:\n"
            f"<b>Example:</b> <code>9876543210</code>"
        ),
        "UPI":    (
            f"<b>📱 Enter Your UPI ID</b>\n\n"
            f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n\n"
            f"Reply with your UPI ID:\n"
            f"<b>Example:</b> <code>name@okhdfcbank</code>"
        ),
        "BANK":   (
            f"<b>🏦 Enter Bank Details</b>\n\n"
            f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n\n"
            f"Reply in this format:\n"
            f"<code>Account Number\nIFSC Code\nAccount Holder Name</code>"
        ),
        "PAYPAL": (
            f"<b>💵 Enter PayPal Email</b>\n\n"
            f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n\n"
            f"Reply with your PayPal email:\n"
            f"<b>Example:</b> <code>you@gmail.com</code>"
        ),
        "USDT":   (
            f"<b>₿ Enter USDT Wallet (TRC20)</b>\n\n"
            f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n\n"
            f"Reply with your TRC20 address:\n"
            f"<b>Example:</b> <code>TQCp8x...</code>"
        ),
    }
    await query.edit_message_text(
        prompts.get(method, "Please send your payment details."),
        parse_mode='HTML'
    )


async def handle_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if 'withdrawal_method' not in context.user_data:
        await update.message.reply_text(
            "❌ Session expired. Start withdrawal again from Balance.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
        return

    method = context.user_data['withdrawal_method']
    result = await db.process_withdrawal_request(user_id, method, text)

    if not result["success"]:
        await update.message.reply_text(
            "❌ Withdrawal failed. Please try again.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
        context.user_data.clear()
        return

    coins = result["coins"]
    rs = result["rs_amount"]
    wid = result.get("id", "N/A")

    await update.message.reply_text(
        f"<b>✅ Withdrawal Submitted!</b>\n\n"
        f"🪙 <b>{coins:,} coins → ₹{rs:.1f}</b>\n"
        f"📌 Method: {method}\n"
        f"🆔 Request ID: <code>#{wid}</code>\n\n"
        f"⏳ Processing: <b>5–7 working days</b>\n"
        f"💬 Support: @CashyadsSupportBot\n\n"
        f"<i>Use /status to check your withdrawal.</i>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )

    # Notify admin
    admin_id = int(os.getenv("ADMIN_ID", "7836675446"))
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        await context.bot.send_message(
            admin_id,
            f"<b>💸 NEW WITHDRAWAL #{wid}</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"🪙 Coins: {coins:,}\n"
            f"💵 Amount: ₹{rs:.1f}\n"
            f"📌 Method: {method}\n\n"
            f"<b>Payment Details:</b>\n"
            f"<code>{escaped}</code>\n\n"
            f"📅 {date.today()}\n\n"
            f"Use: /setstatus {wid} paid",
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"⚠️ Admin notify error: {e}")

    context.user_data.clear()


async def withdrawal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User checks their withdrawal status"""
    user_id = update.effective_user.id
    history = await db.get_user_withdrawals(user_id)

    if not history:
        await update.message.reply_text(
            "📭 <b>No withdrawals found.</b>\n\nYou haven't made any withdrawal requests yet.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )
        return

    status_emoji = {"pending": "⏳", "processing": "🔄", "paid": "✅", "rejected": "❌"}
    lines = []
    for w in history:
        emoji = status_emoji.get(w["status"], "❓")
        dt = str(w.get("created_at", ""))[:10]
        lines.append(
            f"{emoji} <b>#{w['id']}</b> — ₹{w['rs_amount']:.1f} via {w['method']}\n"
            f"   Status: <i>{w['status']}</i> | {dt}"
        )

    await update.message.reply_text(
        "<b>📜 Your Withdrawal History</b>\n\n" + "\n\n".join(lines),
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML'
    )


# ============================================================
# BACK CALLBACKS
# ============================================================

async def back_to_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    coins = await db.get_coins(user_id)
    rs = coins_to_rs(coins)

    await query.edit_message_text(
        f"<b>💳 Your Balance</b>\n\n"
        f"🪙 <b>{coins:,} coins</b>\n"
        f"💵 ≈ <b>₹{rs:.1f}</b>\n\n"
        f"Ready to withdraw?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]]),
        parse_mode='HTML'
    )


async def back_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💳 Paytm",        callback_data="withdraw_paytm")],
        [InlineKeyboardButton("📱 UPI",           callback_data="withdraw_upi")],
        [InlineKeyboardButton("🏦 Bank Transfer", callback_data="withdraw_bank")],
        [InlineKeyboardButton("💵 PayPal",        callback_data="withdraw_paypal")],
        [InlineKeyboardButton("₿ USDT (TRC20)",   callback_data="withdraw_usdt")],
        [InlineKeyboardButton("⬅️ Back",          callback_data="back_balance")],
    ]
    await query.edit_message_text(
        "<b>💳 Choose Payment Method</b>\n\n"
        "<i>Select your preferred withdrawal method:</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
