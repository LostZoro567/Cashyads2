import os
import random
import string
from datetime import date, timedelta, datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ── Constants ────────────────────────────────────────────────
COINS_PER_RS        = 100
MIN_WITHDRAW_COINS  = 38000
MIN_REFERRALS       = 12
MAX_ENERGY = 5
ENERGY_RECHARGE_MINUTES = 24

COIN_REWARDS = {
    "ad_values":               [300, 320, 350, 380, 400, 420, 450, 480, 500],
    "daily_bonus":             500,
    "referral_join":           4000,
    "referral_commission_pct": 0.05,
    "task_reward":             2500,
    "milestone_10_ads":        1000,
    "milestone_50_ads":        5000,
    "milestone_5_refs":        2000,
}

SPIN_PRIZES = [
    {"label": "💀 Nothing",    "coins": 0,    "weight": 30},
    {"label": "🪙 100 Coins",  "coins": 100,  "weight": 25},
    {"label": "🪙 250 Coins",  "coins": 250,  "weight": 20},
    {"label": "🪙 500 Coins",  "coins": 500,  "weight": 13},
    {"label": "🪙 1000 Coins", "coins": 1000, "weight": 8},
    {"label": "💎 2500 Coins", "coins": 2500, "weight": 3},
    {"label": "🎰 5000 Coins", "coins": 5000, "weight": 1},
]


def coins_to_rs(coins: int) -> float:
    return round(coins / COINS_PER_RS, 2)


def spin_wheel() -> dict:
    population = [p for p in SPIN_PRIZES for _ in range(p["weight"])]
    return random.choice(population)


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


# ── In-process cache (per-process, clears on restart) ────────
# Stores: { user_id: {"data": {...}, "ts": datetime} }
_user_cache: dict = {}
_CACHE_TTL_SECONDS = 30   # cache user row for 30 s


def _cache_get(user_id: int):
    entry = _user_cache.get(user_id)
    if entry and (datetime.now() - entry["ts"]).total_seconds() < _CACHE_TTL_SECONDS:
        return entry["data"]
    return None


def _cache_set(user_id: int, data: dict):
    _user_cache[user_id] = {"data": data, "ts": datetime.now()}


def _cache_del(user_id: int):
    _user_cache.pop(user_id, None)


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

    # ── USER ────────────────────────────────────────────────────

    async def get_user(self, user_id: int):
        cached = _cache_get(user_id)
        if cached is not None:
            return cached
        try:
            r = self.client.table("users").select("*").eq("user_id", user_id).execute()
            data = r.data[0] if r.data else None
            if data:
                _cache_set(user_id, data)
            return data
        except:
            return None

    async def get_referrer_by_code(self, referral_code: str):
        try:
            r = self.client.table("users").select(
                "user_id,coins,referrals,weekly_coins,weekly_reset_date"
            ).eq("referral_code", referral_code).execute()
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
        # Use cache first — avoids DB hit on every /start
        if _cache_get(user_id) is not None:
            # Just bump last_active cheaply (fire-and-forget style)
            try:
                self.client.table("users").update(
                    {"last_active": date.today().isoformat()}
                ).eq("user_id", user_id).execute()
            except:
                pass
            return

        user = await self.get_user(user_id)
        if user:
            try:
                self.client.table("users").update(
                    {"last_active": date.today().isoformat()}
                ).eq("user_id", user_id).execute()
            except:
                pass
            return

        referral_code = f"REF_{user_id}_{random.randint(1000,9999)}"
        ws = _week_start()
        user_data = {
            "user_id":           user_id,
            "username":          username or f"User{user_id}",
            "coins":             0,
            "referrals":         0,
            "referral_code":     referral_code,
            "total_ads_watched": 0,
            "streak":            0,
            "last_active":       date.today().isoformat(),
            "last_bonus_date":   None,
            "last_spin_date":    None,
            "weekly_coins":      0,
            "weekly_reset_date": ws,
        }
        try:
            self.client.table("users").insert(user_data).execute()
            _cache_set(user_id, user_data)
            self._bump_total_users()
            print(f"👤 NEW user {user_id} | code: {referral_code}")
        except Exception as e:
            print(f"⚠️ Create user error: {e}")

    def _bump_total_users(self):
        """Best-effort stats increment — not awaited."""
        try:
            r = self.client.table("bot_stats").select("total_users").eq("id", 1).execute()
            if r.data:
                self.client.table("bot_stats").update(
                    {"total_users": int(r.data[0]["total_users"]) + 1}
                ).eq("id", 1).execute()
            else:
                self.client.table("bot_stats").insert({"id": 1, "total_users": 1}).execute()
        except:
            pass

    # ── COINS (single update, no extra get_user) ─────────────────

    async def get_coins(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user.get("coins", 0)) if user else 0

    async def _add_coins_to_user(self, user: dict, amount: int) -> int:
        """
        Core coin update — takes an already-fetched user dict.
        Does ONE DB write. Returns new total.
        """
        user_id  = user["user_id"]
        new_total = max(0, int(user.get("coins", 0)) + amount)
        ws        = _week_start()
        user_ws   = user.get("weekly_reset_date", "")
        weekly    = int(user.get("weekly_coins", 0)) if user_ws == ws else 0
        new_weekly = weekly + max(amount, 0)

        update = {
            "coins":             new_total,
            "weekly_coins":      new_weekly,
            "weekly_reset_date": ws,
        }
        try:
            self.client.table("users").update(update).eq("user_id", user_id).execute()
            # Update cache in-place so next read is instant
            cached = _cache_get(user_id) or {}
            cached.update(update)
            _cache_set(user_id, cached)
            print(f"🪙 {user_id}: {'+' if amount>=0 else ''}{amount} = {new_total}")
        except Exception as e:
            print(f"❌ coin update error: {e}")
        return new_total

    async def add_coins(self, user_id: int, amount: int) -> int:
        """Public API — fetches user if needed."""
        user = await self.get_user(user_id)
        if not user:
            return 0
        return await self._add_coins_to_user(user, amount)

    # ── Energy ( 5 energy in 2hr ) ─────────────────
    
    async def get_and_update_energy(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"energy": 0, "next_recharge_seconds": 0}

        now = datetime.now()
        
        # Fallbacks for existing users who might not have these columns yet
        current_energy = user.get("energy")
        if current_energy is None:
            current_energy = MAX_ENERGY
            
        last_update_str = user.get("last_energy_update")
        if not last_update_str:
            last_update = now
        else:
            try:
                last_update = datetime.fromisoformat(last_update_str)
            except:
                last_update = now

        # If energy is already full, reset the timer to 0
        if current_energy >= MAX_ENERGY:
            return {"energy": MAX_ENERGY, "next_recharge_seconds": 0, "last_update": last_update}

        # Calculate time passed
        time_passed = (now - last_update).total_seconds()
        energy_to_add = int(time_passed // (ENERGY_RECHARGE_MINUTES * 60))

        # Add regenerated energy
        if energy_to_add > 0:
            new_energy = min(MAX_ENERGY, current_energy + energy_to_add)
            
            # Keep the leftover seconds so the timer is perfectly accurate
            remainder_seconds = time_passed % (ENERGY_RECHARGE_MINUTES * 60)
            new_last_update = now - timedelta(seconds=remainder_seconds)
            
            # Update Database
            update = {
                "energy": new_energy,
                "last_energy_update": new_last_update.isoformat()
            }
            self.client.table("users").update(update).eq("user_id", user_id).execute()
            
            # Update cache
            cached = _cache_get(user_id) or user
            cached.update(update)
            _cache_set(user_id, cached)
            
            current_energy = new_energy
            last_update = new_last_update

        # Calculate exactly how many seconds until the next +1 energy
        next_recharge_seconds = 0
        if current_energy < MAX_ENERGY:
            time_passed = (datetime.now() - last_update).total_seconds()
            next_recharge_seconds = max(0, (ENERGY_RECHARGE_MINUTES * 60) - time_passed)

        return {"energy": current_energy, "next_recharge_seconds": next_recharge_seconds, "last_update": last_update}
    
    # ── AD WATCH (was 7+ queries, now 3) ─────────────────────────

    async def reward_ad_watch(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"coins": 0, "total_coins": 0, "ads_watched": 0, "milestone": None}

        coins     = random.choice(COIN_REWARDS["ad_values"])
        ads       = int(user.get("total_ads_watched", 0)) + 1
        ws        = _week_start()
        user_ws   = user.get("weekly_reset_date", "")
        weekly    = int(user.get("weekly_coins", 0)) if user_ws == ws else 0
        new_coins = max(0, int(user.get("coins", 0)) + coins)

        # ONE single DB write for coins + ads counter
        update = {
            "coins":             new_coins,
            "weekly_coins":      weekly + coins,
            "weekly_reset_date": ws,
            "total_ads_watched": ads,
            "last_active":       date.today().isoformat(),
        }
        self.client.table("users").update(update).eq("user_id", user_id).execute()
        cached = _cache_get(user_id) or {}
        cached.update(update)
        _cache_set(user_id, cached)

        # Daily ad counter — separate table, 1 upsert
        self._increment_daily_ads_sync(user_id)

        # Referral commission — only if referrer exists (cached)
        self._pay_commission_sync(user_id, coins)

        # Milestone check (pure math, no extra DB unless milestone hit)
        milestone = None
        milestones = {10: 1000, 50: 5000, 100: 10000, 500: 25000}
        if ads in milestones:
            bonus = milestones[ads]
            cached2 = _cache_get(user_id) or cached
            await self._add_coins_to_user(cached2, bonus)
            milestone = {"ads": ads, "bonus_coins": bonus}

        return {"coins": coins, "total_coins": new_coins, "ads_watched": ads, "milestone": milestone}

    def _increment_daily_ads_sync(self, user_id: int):
        """Fire-and-forget daily counter — doesn't block the reply."""
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_ad_counts").select("count").eq(
                "user_id", user_id
            ).eq("ad_date", today).execute()
            if r.data:
                self.client.table("daily_ad_counts").update(
                    {"count": int(r.data[0]["count"]) + 1}
                ).eq("user_id", user_id).eq("ad_date", today).execute()
            else:
                self.client.table("daily_ad_counts").insert(
                    {"user_id": user_id, "ad_date": today, "count": 1}
                ).execute()
        except Exception as e:
            print(f"⚠️ daily_ads error: {e}")

    def _pay_commission_sync(self, new_user_id: int, coins_earned: int):
        """Pay referrer commission — best-effort, doesn't block."""
        try:
            r = self.client.table("referral_history").select("referrer_id").eq(
                "new_user_id", new_user_id
            ).execute()
            if not r.data:
                return
            referrer_id = r.data[0]["referrer_id"]
            commission  = int(coins_earned * COIN_REWARDS["referral_commission_pct"])
            if commission <= 0:
                return
            ref_user = _cache_get(referrer_id)
            if ref_user:
                self.client.table("users").update({
                    "coins":        max(0, int(ref_user.get("coins", 0)) + commission),
                    "weekly_coins": int(ref_user.get("weekly_coins", 0)) + commission,
                }).eq("user_id", referrer_id).execute()
                ref_user["coins"] = max(0, int(ref_user.get("coins", 0)) + commission)
                _cache_set(referrer_id, ref_user)
            else:
                # referrer not in cache — skip to avoid extra DB call
                pass
        except Exception as e:
            print(f"⚠️ commission error: {e}")

    # ── DAILY BONUS (was 3 writes, now 1) ───────────────────────

    async def give_daily_bonus(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"success": False, "already_claimed": False}

        today_str       = date.today().isoformat()
        last_bonus_raw  = str(user.get("last_bonus_date", "") or "")

        if last_bonus_raw[:10] == today_str:
            return {"success": False, "already_claimed": True, "streak": int(user.get("streak", 0))}

        streak = int(user.get("streak", 0))
        if last_bonus_raw:
            try:
                last_date = date.fromisoformat(last_bonus_raw[:10])
                diff = (date.today() - last_date).days
                streak = (streak + 1) if diff == 1 else 1
            except:
                streak = 1
        else:
            streak = 1

        multiplier  = 3 if streak >= 30 else (2 if streak >= 7 else 1)
        coins_earned = COIN_REWARDS["daily_bonus"] * multiplier
        ws           = _week_start()
        user_ws      = user.get("weekly_reset_date", "")
        weekly       = int(user.get("weekly_coins", 0)) if user_ws == ws else 0
        new_coins    = int(user.get("coins", 0)) + coins_earned

        # ONE write: coins + streak + bonus date
        update = {
            "coins":             new_coins,
            "weekly_coins":      weekly + coins_earned,
            "weekly_reset_date": ws,
            "streak":            streak,
            "last_bonus_date":   today_str,
        }
        self.client.table("users").update(update).eq("user_id", user_id).execute()
        cached = _cache_get(user_id) or {}
        cached.update(update)
        _cache_set(user_id, cached)

        return {"success": True, "coins": coins_earned, "streak": streak, "multiplier": multiplier}

    # ── SPIN (was 3 DB ops, now 1) ───────────────────────────────

    async def can_spin(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        last = str(user.get("last_spin_date", "") or "")
        return last[:10] != date.today().isoformat()

    async def do_spin(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"success": False, "reason": "user_not_found"}
        last = str(user.get("last_spin_date", "") or "")
        if last[:10] == date.today().isoformat():
            return {"success": False, "reason": "already_spun"}

        prize    = spin_wheel()
        ws       = _week_start()
        user_ws  = user.get("weekly_reset_date", "")
        weekly   = int(user.get("weekly_coins", 0)) if user_ws == ws else 0
        new_coins = int(user.get("coins", 0)) + prize["coins"]

        update = {
            "coins":             new_coins,
            "weekly_coins":      weekly + prize["coins"],
            "weekly_reset_date": ws,
            "last_spin_date":    date.today().isoformat(),
        }
        self.client.table("users").update(update).eq("user_id", user_id).execute()
        cached = _cache_get(user_id) or {}
        cached.update(update)
        _cache_set(user_id, cached)

        return {"success": True, "prize": prize, "total_coins": new_coins}

    # ── REFERRAL ─────────────────────────────────────────────────

    async def process_referral(self, user_id: int, referrer_code: str) -> bool:
        if await self.user_already_referred(user_id):
            return False
        try:
            referrer = await self.get_referrer_by_code(referrer_code)
            if not referrer or referrer["user_id"] == user_id:
                return False

            referrer_id   = referrer["user_id"]
            bonus         = COIN_REWARDS["referral_join"]
            new_ref_count = int(referrer.get("referrals", 0)) + 1
            ws            = _week_start()
            ref_ws        = referrer.get("weekly_reset_date", "")
            weekly        = int(referrer.get("weekly_coins", 0)) if ref_ws == ws else 0

            update = {
                "coins":             int(referrer.get("coins", 0)) + bonus,
                "weekly_coins":      weekly + bonus,
                "weekly_reset_date": ws,
                "referrals":         new_ref_count,
            }
            self.client.table("users").update(update).eq("user_id", referrer_id).execute()
            _cache_del(referrer_id)

            # Milestone bonus (no extra get_user — use referrer dict)
            milestone_coins = {5: 2000, 10: 4000, 25: 10000, 50: 25000}.get(new_ref_count)
            if milestone_coins:
                self.client.table("users").update({
                    "coins": int(referrer.get("coins", 0)) + bonus + milestone_coins
                }).eq("user_id", referrer_id).execute()
                _cache_del(referrer_id)

            self.client.table("referral_history").insert({
                "new_user_id":   user_id,
                "referrer_id":   referrer_id,
                "referral_code": referrer_code,
                "created_at":    date.today().isoformat(),
            }).execute()
            print(f"✅ REFERRAL: {user_id} → {referrer_id}")
            return True
        except Exception as e:
            print(f"❌ Referral error: {e}")
            return False

    # ── LEADERBOARD ──────────────────────────────────────────────

    async def get_weekly_leaderboard(self, limit: int = 10) -> list:
        try:
            r = self.client.table("users").select(
                "username,weekly_coins,weekly_reset_date"
            ).eq("weekly_reset_date", _week_start()).order(
                "weekly_coins", desc=True
            ).limit(limit).execute()
            return r.data if r.data else []
        except:
            return []

    async def get_user_rank(self, user_id: int) -> int:
        """Single query — count users with more weekly coins."""
        try:
            user = await self.get_user(user_id)
            if not user:
                return 0
            ws          = _week_start()
            user_weekly = int(user.get("weekly_coins", 0)) if user.get("weekly_reset_date") == ws else 0
            r = self.client.table("users").select("user_id", count="exact").eq(
                "weekly_reset_date", ws
            ).gt("weekly_coins", user_weekly).execute()
            return (r.count or 0) + 1
        except:
            return 0

    # ── WITHDRAWAL ───────────────────────────────────────────────

    async def can_withdraw(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"can": False, "reason": "User not found"}
        coins     = int(user.get("coins", 0))
        referrals = int(user.get("referrals", 0))
        if coins < MIN_WITHDRAW_COINS:
            return {"can": False, "reason": f"Need {MIN_WITHDRAW_COINS-coins:,} more coins ({coins:,}/{MIN_WITHDRAW_COINS:,})"}
        if referrals < MIN_REFERRALS:
            return {"can": False, "reason": f"Need {MIN_REFERRALS-referrals} more referrals ({referrals}/{MIN_REFERRALS})"}
        return {"can": True, "coins": coins, "rs": coins_to_rs(coins), "referrals": referrals}

    async def process_withdrawal_request(self, user_id: int, method: str, details: str) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {"success": False}
        coins     = int(user.get("coins", 0))
        rs_amount = coins_to_rs(coins)

        self.client.table("users").update({"coins": 0}).eq("user_id", user_id).execute()
        _cache_del(user_id)

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
            await self.add_coins(user_id, coins)
            print(f"❌ Withdrawal error: {e}")
            return {"success": False}

    async def get_user_withdrawals(self, user_id: int) -> list:
        try:
            r = self.client.table("withdrawals").select(
                "id,coins,rs_amount,method,status,created_at"
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

    # ── TASKS ────────────────────────────────────────────────────

    async def get_user_daily_tasks(self, user_id: int) -> dict:
        try:
            r = self.client.table("daily_tasks").select("*").eq(
                "user_id", user_id
            ).eq("task_date", date.today().isoformat()).execute()
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
            r = self.client.table("daily_task_codes").select("*").eq(
                "secret_code", code
            ).eq("created_date", today).execute()
            if not r.data:
                return {"valid": False, "reason": "Code not found or expired"}
            code_data = r.data[0]
            used = self.client.table("task_code_usage").select("id").eq(
                "code_id", code_data["id"]
            ).eq("user_id", user_id).execute()
            if used.data:
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
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_ad_counts").select("count").eq(
                "user_id", user_id
            ).eq("ad_date", today).execute()
            return int(r.data[0]["count"]) if r.data else 0
        except:
            return 0

    async def increment_daily_ads(self, user_id: int) -> int:
        self._increment_daily_ads_sync(user_id)
        return 0

    async def complete_task(self, user_id: int, task_type: str) -> bool:
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

    # ── ADMIN / BROADCAST ────────────────────────────────────────

    async def get_total_user_count(self) -> int:
        try:
            r = self.client.table("bot_stats").select("total_users").eq("id", 1).execute()
            return int(r.data[0]["total_users"]) if r.data else 0
        except:
            return 0

    async def get_active_users(self) -> list:
        return await self.get_all_user_ids()

    async def get_all_user_ids(self) -> list:
        try:
            all_ids = []
            offset  = 0
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
            _cache_del(user_id)
            return True
        except:
            return False

    async def generate_daily_codes(self) -> list:
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_task_codes").select("id").eq("created_date", today).execute()
            if r.data and len(r.data) >= 3:
                return await self.get_daily_codes()
            self.client.table("daily_task_codes").delete().lt("created_date", today).execute()
            codes = [
                {"task_number": n, "secret_code": ''.join(random.choices(string.ascii_uppercase + string.digits, k=8)), "created_date": today}
                for n in range(1, 4)
            ]
            self.client.table("daily_task_codes").insert(codes).execute()
            print(f"📋 Generated codes: {[c['secret_code'] for c in codes]}")
            return codes
        except Exception as e:
            print(f"❌ generate_daily_codes error: {e}")
            return []

    async def get_daily_codes(self) -> list:
        try:
            today = date.today().isoformat()
            r = self.client.table("daily_task_codes").select("*").eq(
                "created_date", today
            ).order("task_number").execute()
            return r.data if r.data else []
        except:
            return []


db = SupabaseDB()
