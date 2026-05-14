"""@Investree_bot — Investment system Telegram agent.

Thin wrapper that runs the existing bot logic with a dedicated token
for the investment-focused Telegram bot.
"""

import os

# Override token BEFORE importing main
os.environ["TELEGRAM_BOT_TOKEN"] = "7991054730:AAHJdDXdeezGnZRz80p82jDxkfOYHRScivs"

# Also set a distinct bot name for logging
os.environ.setdefault("BOT_NAME", "Investree")

from main import main

if __name__ == "__main__":
    main()
