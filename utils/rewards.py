import random

# Kept for backward compatibility — main logic is in supabase.py COIN_REWARDS
def generate_reward() -> int:
    """Returns a random coin reward for watching one ad."""
    values = [300, 320, 350, 380, 400, 420, 450, 480, 500]
    return random.choice(values)
