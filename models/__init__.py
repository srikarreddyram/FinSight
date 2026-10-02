"""Module 5: prediction engine (panel, walk-forward validation, ranker, backtest).

FINSIGHT_THREADS caps the CPU threads and worker processes the heavy jobs use (default 6).
"""

import os

THREADS = int(os.environ.get("FINSIGHT_THREADS", "6"))
