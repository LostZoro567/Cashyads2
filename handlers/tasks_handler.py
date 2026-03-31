from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.supabase import db, coins_to_rs, COIN_REWARDS
from datetime import date
import os

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "CashyAds")  # without @


async def tasks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's tasks and their completion status"""
    user_id = update.effective_user.id
    await _show_tasks(update.message.reply_text, user_id, context)


async def _show_tasks(reply_fn, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(user_id)
    if not user:
        await reply_fn("❌ User not found!", parse_mode='HTML')
        return

    today = date.today().isoformat()
    ads_today = int(user.get("total_ads_watched", 0))  # cumulative; use daily task row for daily count
    referrals_total = int(user.get("referrals", 0))

    # Get task completion records for today
    task_done = {}
    try:
        r = db.client.table("task_completions").select("task_type").eq(
            "user_id", user_id
        ).eq("completed_date", today).execute()
        for row in (r.data or []):
            task_done[row["task_type"]] = True
    except:
        pass

    # Daily task row (code tasks)
    daily_task = await db.get_user_daily_tasks(user_id)
    codes_done = int(daily_task.get("tasks_completed", 0)) if daily_task else 0

    task_reward = COIN_REWARDS["task_reward"]

    # Build task list
    def status(done): return "✅" if done else "🔲"

    t1_done = task_done.get("channel_join", False)
    t2_done = task_done.get("watch_5_ads", False)
    t3_done = task_done.get("share_bot", False)
    t4_done = codes_done >= 1

    keyboard_rows = []
    if not t1_done:
        keyboard_rows.append([InlineKeyboardButton("✅ I Joined the Channel", callback_data="task_check_channel")])
    if not t2_done:
        keyboard_rows.append([InlineKeyboardButton("✅ I Watched 5 Ads Today", callback_data="task_check_ads")])
    if not t3_done:
        keyboard_rows.append([InlineKeyboardButton("✅ I Shared the Bot", callback_data="task_check_share")])
    if not t4_done:
        keyboard_rows.append([InlineKeyboardButton("🔑 Submit Task Code", callback_data="task_enter_code")])

    total_earned_today = (
        (task_reward if t1_done else 0) +
        (task_reward if t2_done else 0) +
        (task_reward if t3_done else 0) +
        (codes_done * task_reward)
    )

    await reply_fn(
        f"<b>📋 Daily Tasks</b>\n"
        f"<i>Reset every midnight</i>\n\n"
        f"{status(t1_done)} <b>Task 1:</b> Join @{CHANNEL_USERNAME}\n"
        f"   🪙 +{task_reward:,} coins\n\n"
        f"{status(t2_done)} <b>Task 2:</b> Watch 5 ads today\n"
        f"   🪙 +{task_reward:,} coins\n\n"
        f"{status(t3_done)} <b>Task 3:</b> Share the bot link\n"
        f"   🪙 +{task_reward:,} coins\n\n"
        f"{status(t4_done)} <b>Task 4:</b> Submit today's secret code\n"
        f"   🪙 +{task_reward:,} coins\n"
        f"   <i>(Code posted daily in @{CHANNEL_USERNAME})</i>\n\n"
        f"💰 Earned today: <b>{total_earned_today:,} coins</b>",
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
        parse_mode='HTML'
    )


# ============================================================
# TASK CALLBACK HANDLERS
# ============================================================

async def task_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data  # e.g. "task_check_channel"

    if action == "task_check_channel":
        await _handle_channel_task(query, user_id, context)

    elif action == "task_check_ads":
        await _handle_ads_task(query, user_id, context)

    elif action == "task_check_share":
        await _handle_share_task(query, user_id, context)

    elif action == "task_enter_code":
        context.user_data['awaiting_task_code'] = True
        await query.edit_message_text(
            "<b>🔑 Enter Today's Code</b>\n\n"
            "Send the secret code posted in the channel.\n\n"
            f"📢 @{CHANNEL_USERNAME}",
            parse_mode='HTML'
        )


async def _handle_channel_task(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Verify if user actually joined the channel"""
    try:
        member = await context.bot.get_chat_member(
            chat_id=f"@{CHANNEL_USERNAME}",
            user_id=user_id
        )
        if member.status in ("member", "administrator", "creator"):
            done = await db.complete_task(user_id, "channel_join")
            if done:
                await query.edit_message_text(
                    f"<b>✅ Channel Task Complete!</b>\n\n"
                    f"🪙 <b>+{COIN_REWARDS['task_reward']:,} coins</b> added!\n\n"
                    f"Use 📋 Tasks to see your progress.",
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text(
                    "✅ <b>Already completed!</b>\n\nYou already got this reward today.",
                    parse_mode='HTML'
                )
        else:
            await query.edit_message_text(
                f"<b>❌ Not a member yet!</b>\n\n"
                f"Please join @{CHANNEL_USERNAME} first, then click the button again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📢 Join @{CHANNEL_USERNAME}", url=f"https://t.me/{CHANNEL_USERNAME}")],
                    [InlineKeyboardButton("✅ Check Again", callback_data="task_check_channel")],
                ]),
                parse_mode='HTML'
            )
    except Exception as e:
        print(f"⚠️ Channel check error: {e}")
        # If bot can't check (not admin in channel), just award
        done = await db.complete_task(user_id, "channel_join")
        if done:
            await query.edit_message_text(
                f"<b>✅ Channel Task Complete!</b>\n\n"
                f"🪙 <b>+{COIN_REWARDS['task_reward']:,} coins</b> added!",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                "✅ Already completed today!", parse_mode='HTML'
            )


async def _handle_ads_task(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Check if user has watched at least 5 ads since task tracking started today"""
    daily_task = await db.get_user_daily_tasks(user_id)
    # We track daily ads in a separate simple way: check task row
    # Use task_completions to see if already done; if not, check ads count
    today = date.today().isoformat()
    try:
        r = db.client.table("task_completions").select("id").eq(
            "user_id", user_id
        ).eq("task_type", "watch_5_ads").eq("completed_date", today).execute()
        if r.data:
            await query.edit_message_text("✅ <b>Already completed!</b>", parse_mode='HTML')
            return
    except:
        pass

    # Check daily ad count from daily_tasks table
    ads_today = 0
    if daily_task:
        ads_today = int(daily_task.get("tasks_completed", 0))

    # Fallback: use total from user (approximate — better than nothing)
    user = await db.get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Error. Try again.", parse_mode='HTML')
        return

    # We'll track daily ad watch count via a dedicated column or the daily_tasks table
    # For now, we check if the user has watched >= 5 ads logged today
    # The web_app_data handler must call db.increment_daily_ads(user_id) each watch
    daily_ads = await db.get_daily_ad_count(user_id)

    if daily_ads >= 5:
        done = await db.complete_task(user_id, "watch_5_ads")
        if done:
            await query.edit_message_text(
                f"<b>✅ Ads Task Complete!</b>\n\n"
                f"📺 Watched {daily_ads} ads today\n"
                f"🪙 <b>+{COIN_REWARDS['task_reward']:,} coins</b> added!",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text("✅ <b>Already completed!</b>", parse_mode='HTML')
    else:
        await query.edit_message_text(
            f"<b>📺 Watch 5 Ads Task</b>\n\n"
            f"Progress: <b>{daily_ads}/5 ads</b> watched today\n\n"
            f"Watch {5 - daily_ads} more ads, then come back!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Again", callback_data="task_check_ads")]
            ]),
            parse_mode='HTML'
        )


async def _handle_share_task(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Self-reported share task — award once per day"""
    done = await db.complete_task(user_id, "share_bot")
    if done:
        await query.edit_message_text(
            f"<b>✅ Share Task Complete!</b>\n\n"
            f"Thanks for sharing! 🙏\n"
            f"🪙 <b>+{COIN_REWARDS['task_reward']:,} coins</b> added!",
            parse_mode='HTML'
        )
    else:
        await query.edit_message_text(
            "✅ <b>Already completed today!</b>",
            parse_mode='HTML'
        )


async def handle_task_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input when user is submitting a task code"""
    user_id = update.effective_user.id
    code = update.message.text.strip().upper()

    result = await db.check_task_code(code, user_id)
    if not result["valid"]:
        await update.message.reply_text(
            f"<b>❌ Invalid Code</b>\n\n"
            f"Reason: {result['reason']}\n\n"
            f"<i>Codes are posted daily in @{CHANNEL_USERNAME}</i>",
            parse_mode='HTML'
        )
        context.user_data.pop('awaiting_task_code', None)
        return

    code_id = result["code_id"]
    await db.mark_code_used(code_id, user_id)

    # Update daily task progress
    daily_task = await db.get_user_daily_tasks(user_id)
    codes_done = int(daily_task.get("tasks_completed", 0)) if daily_task else 0
    new_count = codes_done + 1

    await db.create_or_update_daily_task(user_id, tasks_completed=new_count)
    await db.add_coins(user_id, COIN_REWARDS["task_reward"])

    context.user_data.pop('awaiting_task_code', None)

    await update.message.reply_text(
        f"<b>✅ Code Accepted!</b>\n\n"
        f"🔑 Task {result['task_number']} completed!\n"
        f"🪙 <b>+{COIN_REWARDS['task_reward']:,} coins</b> added!\n\n"
        f"Check 📋 Tasks to see your progress.",
        parse_mode='HTML'
    )
