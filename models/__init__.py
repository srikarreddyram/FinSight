"""Module 5: prediction engine (panel, walk-forward validation, ranker, backtest).

FINSIGHT_THREADS caps the CPU threads and worker processes the heavy jobs use (default 6).
FINSIGHT_UNIVERSE picks the study the models and the dashboard run on: "sp1500" (S&P 500, 400 and 600 members,
the default) or "sp500". Each has its own folder under data/study.
"""

import os
from pathlib import Path

THREADS = int(os.environ.get("FINSIGHT_THREADS", "6"))
UNIVERSE = os.environ.get("FINSIGHT_UNIVERSE", "sp1500")
STUDY_DIR = Path("data/study") / UNIVERSE
INDEXES = {"sp500": ("sp500",), "sp1500": ("sp500", "sp400", "sp600")}  # study universe -> the indexes in it
