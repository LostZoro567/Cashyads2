from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from utils.supabase import db
import os
import asyncio
from datetime import date

ADMIN_ID = int(os.getenv("ADMIN_ID", "7836675446"))

failed_broadcast_users = []


async def broadcast_task(context, admin_id, message, active_users):
    global failed_broadcast_users
    success_count = 0
    failed_count = 0
    total_users = len(active_users)
    failed_broadcast_users = []

    for i, user_id in enumerate(active_users, 1):
        try:
            await context.bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')
            success_count += 1
        except:
            failed_count += 1
            failed_broadcast_users.append(user_id)

        if i % 30 == 0:
            await asyncio.sleep(1)

    try:
        await context.bot.send_message(
            admin_id,
            f"✅ <b>Broadcast COMPLETE!</b>\n\n"
            f"👥 Total: {total_users}\n"
            f"✅ Delivered: {success_count}\n"
            f"❌ Failed: {failed_count}\n"
            f"📈 Rate: {(success_count/total_users*100):.1f}%\n\n"
            f"💡 Run /cleanup to remove {failed_count} failed users",
            parse_mode='HTML'
        )
    except:
        pass


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ <b>Admin only!</b>", parse_mode='HTML')
        return

    if not context.args:
        await update.message.reply_text(
            "📢 <b>Usage:</b>\n<code>/broadcast Hello everyone!</code>",
            parse_mode='HTML'
        )
        return

    active_users = await db.get_active_users()
    if not active_users:
        await update.message.reply_text("❌ No active users!", parse_mode='HTML')
        return

    if context.bot_data.get('broadcast_running'):
        await update.message.reply_text("⚠️ Broadcast already running!", parse_mode='HTML')
        return

    message = " ".join(context.args)
    context.bot_data['broadcast_running'] = True

    await update.message.reply_text(
        f"📤 <b>Broadcast started!</b>\n\n"
        f"👥 Users: {len(active_users)}\n"
        f"📨 Message: {message[:50]}...",
        parse_mode='HTML'
    )
    asyncio.create_task(_broadcast_wrapper(context, update.effective_user.id, message, active_users))


async def _broadcast_wrapper(context, admin_id, message, active_users):
    try:
        await broadcast_task(context, admin_id, message, active_users)
    finally:
        context.bot_data['broadcast_running'] = False


async def cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global failed_broadcast_users

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ <b>Admin only!</b>", parse_mode='HTML')
        return

    if context.bot_data.get('cleanup_running'):
        await update.message.reply_text("⚠️ Cleanup already running!", parse_mode='HTML')
        return

    if not failed_broadcast_users:
        await update.message.reply_text(
            "ℹ️ No failed users to clean. Run /broadcast first.",
            parse_mode='HTML'
        )
        return

    context.bot_data['cleanup_running'] = True
    total = len(failed_broadcast_users)
    await update.message.reply_text(f"🧹 Removing {total} blocked users...", parse_mode='HTML')
    asyncio.create_task(_cleanup_wrapper(context, update.effective_user.id))


async def _cleanup_wrapper(context, admin_id):
    global failed_broadcast_users
    try:
        total = len(failed_broadcast_users)
        deleted = 0
        for i, user_id in enumerate(failed_broadcast_users, 1):
            try:
                if await db.delete_user(user_id):
                    deleted += 1
            except:
                pass
            if i % 20 == 0:
                await asyncio.sleep(0.5)

        remaining = len(await db.get_all_user_ids())
        await context.bot.send_message(
            admin_id,
            f"✅ <b>Cleanup COMPLETE!</b>\n\n"
            f"🗑️ Deleted: {deleted}/{total}\n"
            f"👥 Remaining: {remaining}",
            parse_mode='HTML'
        )
        failed_broadcast_users = []
    finally:
        context.bot_data['cleanup_running'] = False


async def setstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /setstatus <withdrawal_id> <status>"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: <code>/setstatus &lt;id&gt; &lt;status&gt;</code>\n"
            "Status options: pending, processing, paid, rejected",
            parse_mode='HTML'
        )
        return

    try:
        wid = int(context.args[0])
        status = context.args[1].lower()
        valid_statuses = ["pending", "processing", "paid", "rejected"]
        if status not in valid_statuses:
            await update.message.reply_text(f"❌ Invalid status. Use: {', '.join(valid_statuses)}")
            return

        success = await db.set_withdrawal_status(wid, status)
        if success:
            await update.message.reply_text(f"✅ Withdrawal #{wid} → <b>{status}</b>", parse_mode='HTML')
        else:
            await update.message.reply_text(f"❌ Failed to update withdrawal #{wid}")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Use a number.")


async def pending_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: list pending withdrawals"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return

    withdrawals = await db.get_pending_withdrawals()
    if not withdrawals:
        await update.message.reply_text("📭 No pending withdrawals!")
        return

    lines = []
    for w in withdrawals[:20]:
        lines.append(
            f"<b>#{w['id']}</b> | User: <code>{w['user_id']}</code>\n"
            f"  ₹{w['rs_amount']:.1f} via {w['method']} | {str(w.get('created_at',''))[:10]}"
        )

    await update.message.reply_text(
        f"<b>💸 Pending Withdrawals ({len(withdrawals)})</b>\n\n" + "\n\n".join(lines),
        parse_mode='HTML'
    )


async def gencode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /gencode — generate today's 3 task codes and display them"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!")
        return

    codes = await db.generate_daily_codes()
    if not codes:
        await update.message.reply_text("❌ Failed to generate codes. Check logs.")
        return

    lines = [f"Task {c['task_number']}: <code>{c['secret_code']}</code>" for c in codes]
    await update.message.reply_text(
        f"<b>🔑 Today's Task Codes ({date.today()})</b>\n\n"
        + "\n".join(lines) +
        "\n\n<i>Post these in your channel!\n"
        "Each code can only be used once per user.</i>",
        parse_mode='HTML'
    )


broadcast_handler  = CommandHandler("broadcast", broadcast)
cleanup_handler    = CommandHandler("cleanup", cleanup)
setstatus_handler  = CommandHandler("setstatus", setstatus)
pending_handler    = CommandHandler("pending", pending_withdrawals)
gencode_handler    = CommandHandler("gencode", gencode)
