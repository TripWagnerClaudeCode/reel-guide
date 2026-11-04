"""Keep tests hermetic: never read the user's env file or send real pushes."""
import os

os.environ["REEL_GUIDE_ENV_FILE"] = os.devnull
for _k in list(os.environ):
    if _k.startswith("REEL_GUIDE_") and _k != "REEL_GUIDE_ENV_FILE":
        del os.environ[_k]
