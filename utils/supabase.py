import os
import random
from datetime import date, timedelta, datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# COIN CONSTANTS  —  1000 coins = 10 Rs  (100 coins = 1 Rs)
# ============================================================
COINS_PER_RS = 100
MIN_WITHDRAW_COINS = 38000   # 38 000 coins = 380 Rs
MIN_REFERRALS = 12

COIN_REWARDS = {
    "ad_values":               [300, 320, 350, 380, 400, 420, 450, 480, 500],
    "daily_bonus":             500,    # 5 Rs
    "referral_join":           4000,   # 40 Rs
    "referral_commission_pct": 0.05,
    "task_reward":             2500,   # 25 Rs per task
    "milestone_10_ads":        1000,
    "milestone_50_ads":        5000,
    "milestone_5_refs":        2000,
}

SPIN_PRIZES = [
    {"label": "💀 Nothing",   "coins": 0,    "weight": 30},
    {"label": "🪙 100 Coins", "coins": 100,  "weight": 25},
    {"label": "🪙 250 Coins", "coins": 250,  "weight": 20},
    {"label": "🪙 500 Coins", "coins": 500,  "weight": 13},
    {"label": "🪙 1000 Coins","coins": 1000, "weight": 8},
    {"label": "💎 2500 Coins","coins": 2500, "weight": 3},
    {"label": "🎰 5000 Coins","coins": 5000, "weight": 1},
]


def coins_to_rs(coins: int) -> float:
    return round(coins / COINS_PER_RS, 2)


def spin_wheel() -> dict:
    population = [p for p in SPIN_PRIZES for _ in range(p["weight"])]
    return random.choice(population)


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


class SupabaseDB:
    def __init__(self):
        self.client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )

    async def init_table(self):
        try:
            self.client.table("users").select("*").limit(0).execute()
            print("✅ DB connected")
        except Exception as e:
            print(f"⚠️ DB init warning: {e}")

    # ============================================================
    # USER MANAGEMENT
    # ============================================================

    async def get_user(self, user_id: int):
        try:
            r = self.client.table("users").select("*").eq("user_id", user_id).execute()
            return r.data[0] if r.data else None
        except:
            return None

    async def get_referrer_by_code(self, referral_code: str):
        try:
            r = self.client.table("users").select("*").eq("referral_code", referral_code).execute()
            return r.data[0] if r.data else None
        except:
            return None

    async def user_already_referred(self, user_id: int) -> bool:
        try:
            r = self.client.table("referral_history").select("id").eq("new_user_id", user_id).execute()
            return len(r.data) > 0
        except:
            return False

    async def create_user_if_not_exists(self, user_id: int, username: str = ""):
        user = await self.get_user(user_id)
        if user:
            await self._touch_last_active(user_id)
            return

        referral_code = f"REF_{user_id}_{random.randint(1000, 9999)}"
        user_data = {
            "user_id":          user_id,
            "username":         username or f"User{user_id}",
            "coins":            0,
            "referrals":        0,
            "referral_code":    referral_code,
            "total_ads_watched":0,
            "streak":           0,
            "last_active":      date.today().isoformat(),
            "last_bonus_date":  None,
            "last_spin_date":   None,
            "weekly_coins":     0,
            "weekly_reset_date":_week_start(),
        }
        try:
            self.client.table("users").insert(user_data).execute()
            await self._increment_total_users()
            print(f"👤 CREATED user {user_id} | code: {referral_code}")
        except Exception as e:
            print(f"⚠️ Create user error: {e}")

    async def _touch_last_active(self, user_id: int):
        try:
            self.client.table("users").update({
                "last_active": date.today().isoformat()
            }).eq("user_id", user_id).execute()
        except:
            pass

    async def _increment_total_users(self):
        try:
            r = self.client.table("bot_stats").select("total_users").eq("id", 1).execute()
            if r.data:
                self.client.table("bot_stats").update({
                    "total_users": int(r.data[0]["total_users"]) + 1
                }).eq("id", 1).execute()
            else:
                self.client.table("bot_stats").insert({"id": 1, "total_users": 1}).execute()
        except:
            pass

    # ============================================================
    # COINS
    # ============================================================

    async def get_coins(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user.get("coins", 0)) if user else 0

    async def add_coins(self, user_id: int, amount: int) -> int:
        """Add (or subtract) coins. Returns new total."""
        user = await self.get_user(user_id)
        if not user:
            return 0

        new_total = max(0, int(user.get("coins", 0)) + amount)

        # Weekly leaderboard reset logic
        ws = _week_start()
        user_ws = user.get("weekly_reset_date", "")
        weekly = int(user.get("weekly_coins", 0)) if user_ws == ws else 0
        new_weekly = weekly + max(amount, 0)

        try:
            self.client.table("users").update({
                "coins":             new_total,
                "weekly_coins":      new_weekly,
                "weekly_reset_date": ws,
            }).eq("user_id", user_id).execute()
            print(f"🪙 {user_id}: {'+' if amount >= 0 else ''}{amount} = {new_total} coins")
            return new_total
        except Exception as e:
            print(f"❌ add_coins error: {e}")
            return int(user.get("coins", 0))

    # ============================================================
    # AD WATCH
    # ============================================================

    async def reward_ad_watch(self, user_id: int) -> dict:
        coins = random.choice(COIN_REWARDS["ad_values"])
        new_total = await self.add_coins(user_id, coins)

        # Increment cumulative and daily ad counters
        user = await self.get_user(user_id)
        ads = int(user.get("total_ads_watched", 0)) + 1
        self.client.table("users").update({"total_ads_watched": ads}).eq("user_id", user_id).execute()
        await self.increment_daily_ads(user_id)

        await self.add_referral_commission(user_id, coins)

        milestone = await self._check_ad_milestones(user_id, ads)
        return {"coins": coins, "total_coins": new_total, "ads_watched": ads, "milestone": milestone}

    async def _check_ad_milestones(self, user_id: int, ads: int):
        milestones = {
            10:  COIN_REWARDS["milestone_10_ads"],
            50:  COIN_REWARDS["milestone_50_ads"],
            100: COIN_REWARDS["milestone_50_ads"] * 2,
            500: COIN_REWARDS["milestone_50_ads"] * 5,
        }
        if ads in milestones:
            bonus = milestones[ads]
            await self.add_coins(user_id, bonus)
            return {"ads": ads, "bonus_coins": bonus}
        return None

    # ============================================================
    # DAILY BONUS + STREAK
    # ============================================================

    async def give_daily_bonus(self, user_id: int) -> dict:
        """
        Returns:
          {"success": False, "already_claimed": True, "streak": N}
          {"success": True, "coins": N, "streak": N, "multiplier": N}
        """
        user = await self.get_user(user_id)
        if not user:
            return {"success": False, "already_claimed": False}

        today = date.today()
        today_str = today.isoformat()
        last_bonus_raw = str(user.get("last_bonus_date", "") or "")

        if last_bonus_raw[:10] == today_str:
            return {"success": False, "already_claimed": True, "streak": int(user.get("streak", 0))}

        # Calculate streak
        streak = int(user.get("streak", 0))
        if last_bonus_raw:
            try:
                last_date = date.fromisoformat(last_bonus_raw[:10])
                diff = (today - last_date).days
                streak = (streak + 1) if diff == 1 else 1
            except:
                streak = 1
        else:
            streak = 1

        # Multiplier
        multiplier = 3 if streak >= 30 else (2 if streak >= 7 else 1)
        coins_earned = COIN_REWARDS["daily_bonus"] * multiplier

        await self.add_coins(user_id, coins_earned)
        self.client.table("users").update({
            "streak":          streak,
            "last_bonus_date": today_str,
        }).eq("user_id", user_id).execute()

        return {"success": True, "coins": coins_earned, "streak": streak, "multiplier": multiplier}

    # ============================================================
    # SPIN WHEEL
    # ============================================================

    async def can_spin(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        last = str(user.get("last_spin_date", "") or "")
        return last[:10] != date.today().isoformat()

    async def do_spin(self, user_id: int) -> dict:
        if not await self.can_spin(user_id):
            return {"success": False, "reason": "already_spun"}

        prize = spin_wheel()
        new_total = await self.add_coins(user_id, prize["coins"])
        self.client.table("users").update({
            "last_spin_date": date.today().isoformat()
        }).eq("user_id", user_id).execute()

        return {"success": True, "prize": prize, "total_coins": new_total}

    # ============================================================
    # REFERRAL
    # ============================================================

    async def process_referral(self, user_id: int, referrer_code: str) -> bool:
        if await self.user_already_referred(user_id):
            return False
        try:
            referrer = await self.get_referrer_by_code(referrer_code)
            if not referrer or referrer["user_id"] == user_id:
                return False

            referrer_id = referrer["user_id"]
            await self.add_coins(referrer_id, COIN_REWARDS["referral_join"])

            new_ref_count = int(referrer.get("referrals", 0)) + 1
            self.client.table("users").update({"referrals": new_ref_count}).eq("user_id", referrer_id).execute()

            await self._check_referral_milestones(referrer_id, new_ref_count)

            self.client.table("referral_history").insert({
                "new_user_id":   user_id,
                "referrer_id":   referrer_id,
                "referral_code": referrer_code,
                "created_at":    date.today().isoformat(),
            }).execute()
            print(f"✅ REFERRAL: {user_id} → {referrer_id} (+{COIN_REWARDS['referral_join']} coins)")
            return True
        except Exception as e:
            print(f"❌ Referral error: {e}")
            return False

    async def _check_referral_milestones(self, user_id: int, ref_count: int):
        milestones = {5: 2000, 10: 4000, 25: 10000, 50: 25000}
        if ref_count in milestones:
            bonus = milestones[ref_count]
            await self.add_coins(user_id, bonus)
            return {"refs": ref_count, "bonus_coins": bonus}
        return None

    async def add_referral_commission(self, new_user_id: int, coins_earned: int):
        try:
            r = self.client.table("referral_history").select("referrer_id").eq("new_user_id", new_user_id).execute()
            if r.data:
                referrer_id = r.data[0]["referrer_id"]
                commission = int(coins_earned * COIN_REWARDS["referral_commission_pct"])
                if commission > 0:
                    await self.add_coins(referrer_id, commission)
        except Exception as e:
            print(f"⚠️ Commission error: {e}")

    # ============================================================
    # LEADERBOARD
    # ============================================================

    async def get_weekly_leaderboard(self, limit: int = 10) -> list:
        try:
            r = self.client.table("users").select(
                "user_id, username, weekly_coins, weekly_reset_date"
            ).eq("weekly_reset_date", _week_start()).order(
                "weekly_coins", desc=True
            ).limit(limit).execute()
            return r.data if r.data else []
        except Exception as e:
            print(f"⚠️ Leaderboard error: {e}")
            return []

    async def get_user_rank(self, user_id: int) -> int:
        try:
            user = await self.get_user(user_id)
            if not user:
                return 0
            ws = _week_start()
            user_weekly = int(user.get("weekly_coins", 0)) if user.get("weekly_reset_date") == ws else 0
            r = self.client.table("users").select("user_id").eq(
                "weekly_reset_date", ws
            ).gt("weekly_coins", user_weekly).execute()
            return len(r.data) + 1
        except:
            return 0

    # ============================================================
    # WITHDRAWAL
    # ============================================================

    async def can_withdraw(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"can": False, "reason": "User not found"}

        coins = int(user.get("coins", 0))
        referrals = int(user.get("referrals", 0))

        if coins < MIN_WITHDRAW_COINS:
            needed = MIN_WITHDRAW_COINS - coins
            return {"can": False, "reason": f"Need {needed:,} more coins (have {coins:,}/{MIN_WITHDRAW_COINS:,})"}
        if referrals < MIN_REFERRALS:
            return {"can": False, "reason": f"Need {MIN_REFERRALS - referrals} more referrals (have {referrals}/{MIN_REFERRALS})"}

        return {"can": True, "coins": coins, "rs": coins_to_rs(coins), "referrals": referrals}

    async def process_withdrawal_request(self, user_id: int, method: str, details: str) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"success": False}

        coins = int(user.get("coins", 0))
        rs_amount = coins_to_rs(coins)

        # Zero out coins first
        self.client.table("users").update({"coins": 0}).eq("user_id", user_id).execute()

        try:
            r = self.client.table("withdrawals").insert({
                "user_id":         user_id,
                "coins":           coins,
                "rs_amount":       rs_amount,
                "method":          method,
                "payment_details": details,
                "status":          "pending",
                "created_at":      datetime.now().isoformat(),
            }).execute()
            wid = r.data[0]["id"] if r.data else None
            print(f"💸 Withdrawal #{wid}: {user_id} → ₹{rs_amount} via {method}")
            return {"success": True, "coins": coins, "rs_amount": rs_amount, "id": wid}
        except Exception as e:
            # Rollback
            await self.add_coins(user_id, coins)
            print(f"❌ Withdrawal DB error: {e}")
            return {"success": False}

    async def get_user_withdrawals(self, user_id: int) -> list:
        try:
            r = self.client.table("withdrawals").select(
                "id, coins, rs_amount, method, status, created_at"
            ).eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
            return r.data if r.data else []
        except:
            return []

    async def set_withdrawal_status(self, withdrawal_id: int, status: str) -> bool:
        try:
            self.client.table("withdrawals").update({
                "status":     status,
                "updated_at": datetime.now().isoformat()
            }).eq("id", withdrawal_id).execute()
            return True
        except:
            return False

    async def get_pending_withdrawals(self) -> list:
        try:
            r = self.client.table("withdrawals").select("*").eq(
                "status", "pending"
            ).order("created_at").execute()
            return r.data if r.data else []
        except:
            return []

    # ============================================================
    # DAILY TASKS
    # ============================================================

    async def get_user_daily_tasks(self, user_id: int) -> dict:
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_tasks").select("*").eq("user_id", user_id).eq("task_date", today).execute()
            return r.data[0] if r.data else None
        except:
            return None

    async def create_or_update_daily_task(self, user_id: int, tasks_completed: int = 0, pending_reward: int = 0):
        try:
            self.client.table("daily_tasks").upsert({
                "user_id":         user_id,
                "task_date":       date.today().isoformat(),
                "tasks_completed": tasks_completed,
                "pending_reward":  pending_reward,
                "last_task_time":  datetime.now().isoformat(),
            }).execute()
        except Exception as e:
            print(f"❌ Task update error: {e}")

    async def check_task_code(self, code: str, user_id: int) -> dict:
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_task_codes").select("*").eq("secret_code", code).eq("created_date", today).execute()
            if not r.data:
                return {"valid": False, "reason": "Code not found or expired"}
            code_data = r.data[0]
            usage_r = self.client.table("task_code_usage").select("id").eq("code_id", code_data["id"]).eq("user_id", user_id).execute()
            if usage_r.data:
                return {"valid": False, "reason": "You already used this code"}
            return {"valid": True, "task_number": code_data["task_number"], "code_id": code_data["id"]}
        except Exception as e:
            print(f"⚠️ Code check error: {e}")
            return {"valid": False, "reason": "Error checking code"}

    async def mark_code_used(self, code_id: int, user_id: int):
        try:
            self.client.table("task_code_usage").insert({
                "code_id":   code_id,
                "user_id":   user_id,
                "used_date": datetime.now().isoformat(),
            }).execute()
        except Exception as e:
            print(f"⚠️ mark_code_used error: {e}")

    async def get_daily_ad_count(self, user_id: int) -> int:
        """How many ads has the user watched today?"""
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_ad_counts").select("count").eq(
                "user_id", user_id
            ).eq("ad_date", today).execute()
            return int(r.data[0]["count"]) if r.data else 0
        except:
            return 0

    async def increment_daily_ads(self, user_id: int) -> int:
        """Increment today's ad count. Returns new count."""
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_ad_counts").select("count").eq(
                "user_id", user_id
            ).eq("ad_date", today).execute()

            if r.data:
                new_count = int(r.data[0]["count"]) + 1
                self.client.table("daily_ad_counts").update({"count": new_count}).eq(
                    "user_id", user_id
                ).eq("ad_date", today).execute()
            else:
                new_count = 1
                self.client.table("daily_ad_counts").insert({
                    "user_id": user_id,
                    "ad_date": today,
                    "count":   1,
                }).execute()
            return new_count
        except Exception as e:
            print(f"⚠️ increment_daily_ads error: {e}")
            return 0

    async def complete_task(self, user_id: int, task_type: str) -> bool:
        """Mark a channel/share task done today and award coins. Returns False if duplicate."""
        try:
            today = date.today().isoformat()
            r = self.client.table("task_completions").select("id").eq(
                "user_id", user_id
            ).eq("task_type", task_type).eq("completed_date", today).execute()
            if r.data:
                return False
            self.client.table("task_completions").insert({
                "user_id":        user_id,
                "task_type":      task_type,
                "completed_date": today,
            }).execute()
            await self.add_coins(user_id, COIN_REWARDS["task_reward"])
            return True
        except Exception as e:
            print(f"⚠️ complete_task error: {e}")
            return False

    # ============================================================
    # ADMIN BROADCAST / CLEANUP
    # ============================================================

    async def get_total_user_count(self) -> int:
        try:
            r = self.client.table("bot_stats").select("total_users").eq("id", 1).execute()
            return int(r.data[0]["total_users"]) if r.data else 0
        except:
            return 0

    async def get_all_user_ids(self) -> list:
        try:
            all_ids = []
            offset = 0
            while True:
                r = self.client.table("users").select("user_id").range(offset, offset + 499).execute()
                if not r.data:
                    break
                all_ids.extend([u["user_id"] for u in r.data])
                offset += 500
            return all_ids
        except:
            return []

    async def delete_user(self, user_id: int) -> bool:
        try:
            self.client.table("users").delete().eq("user_id", user_id).execute()
            self.client.table("referral_history").delete().eq("new_user_id", user_id).execute()
            self.client.table("referral_history").delete().eq("referrer_id", user_id).execute()
            return True
        except:
            return False


    async def generate_daily_codes(self) -> list:
        """Generate 3 unique task codes for today. Admin calls this once per day."""
        import string
        try:
            today = date.today().isoformat()
            # Don't regenerate if already done today
            r = self.client.table("daily_task_codes").select("id").eq("created_date", today).execute()
            if r.data and len(r.data) >= 3:
                print("✅ Daily codes already generated")
                return await self.get_daily_codes()

            # Delete yesterday's codes
            self.client.table("daily_task_codes").delete().lt("created_date", today).execute()

            codes = []
            for task_num in range(1, 4):
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                codes.append({"task_number": task_num, "secret_code": code, "created_date": today})

            self.client.table("daily_task_codes").insert(codes).execute()
            print(f"📋 Generated codes: {[c['secret_code'] for c in codes]}")
            return codes
        except Exception as e:
            print(f"❌ generate_daily_codes error: {e}")
            return []

    async def get_daily_codes(self) -> list:
        """Get today's task codes (for admin display)."""
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_task_codes").select("*").eq(
                "created_date", today
            ).order("task_number").execute()
            return r.data if r.data else []
        except Exception as e:
            print(f"⚠️ get_daily_codes error: {e}")
            return []


db = SupabaseDB()
