from __future__ import annotations
import abc
import asyncio
import multiprocessing as mp
from dataclasses import dataclass
from typing import Generic, TypeVar, Callable, Iterator, AsyncIterator, Optional, Type, List, Any, Tuple, Iterable
from queue import Empty
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import threading
from multiprocessing.context import SpawnContext
from multiprocessing.pool import ThreadPool
import time
import random
import heapq
from tqdm.auto import tqdm
import asyncio
from time import perf_counter
from collections import deque
import sys
import warnings

from .stage import Stage
from .worker import Worker
from .worker_exception import WorkerException


class PipelineTQDM:
    """Handles progress bar functionality for the pipeline."""

    def __init__(self, stages: List[Stage],
                 show_progress: bool = False, show_stage_progress: bool = False, total: Optional[int] = None):
        self.stages = stages
        self.show_progress = show_progress
        self.show_stage_progress = show_stage_progress
        self.progress_bars: List[tqdm] = []
        self.stage_pbars: List[tqdm] = []
        self.stage_times: List[deque] = [deque(maxlen=100) for _ in stages]
        self.stage_start_times: List[Optional[float]] = [None] * len(stages)
        self.stage_processed: List[int] = [0] * len(stages)
        self.stage_total_times: List[float] = [0.0] * len(stages)  # Track cumulative processing time
        self.total = total
        self.init_progress_bars()

    def init_progress_bars(self) -> None:
        """Initialize progress bars and related tracking variables."""
        if not self.show_progress:
            return

        # Create main progress bar
        main_pbar = tqdm(total=self.total,
                         desc="Total Progress",
                         position=0,
                         leave=True)
        self.progress_bars.append(main_pbar)

        if self.show_stage_progress and self.total:
            # Create progress bars for stages
            for i, stage in enumerate(self.stages):
                desc = f"Stage {i+1} ({stage.worker_class.__name__})"
                bar_format = "{l_bar}{bar}| {n_fmt}/{total_fmt}{postfix}"  # Remove default elapsed/remaining
                stage_pbar = tqdm(total=self.total,
                                  desc=desc,
                                  position=i+1,
                                  leave=True,
                                  postfix="",
                                  bar_format=bar_format)
                self.stage_pbars.append(stage_pbar)
            self.progress_bars.extend(self.stage_pbars)

    def update_stage_progress(self, stage_idx: int, result_time: float) -> None:
        """Update progress bar for a specific stage."""
        if stage_idx == len(self.stages)-1:
            self.update_main_progress(1)
        if not (self.show_progress and self.show_stage_progress and self.stage_pbars):
            return

        self.stage_processed[stage_idx] += 1
        self.stage_times[stage_idx].append(result_time)
        self.stage_total_times[stage_idx] += result_time  # Add to cumulative time
        avg_time = sum(self.stage_times[stage_idx]) / len(self.stage_times[stage_idx])

        # Calculate items waiting to be processed
        if stage_idx == 0:
            waiting = self.total - self.stage_processed[0] if self.total else 0
        else:
            waiting = self.stage_processed[stage_idx - 1] - self.stage_processed[stage_idx]

        # Calculate estimated remaining time based on average processing time
        remaining = (self.total - self.stage_processed[stage_idx]) * avg_time if self.total else 0

        # Calculate rate and format it appropriately
        rate = 1 / avg_time if avg_time > 0 else 0
        if rate >= 1:
            rate_str = f"{rate:.2f}it/s"
        else:
            rate_str = f"{1/rate:.2f}s/it"

        # Format elapsed and remaining times in MM:SS format
        def format_time(seconds):
            minutes = int(seconds) // 60
            seconds = int(seconds) % 60
            return f"{minutes:02d}:{seconds:02d}"

        elapsed_str = format_time(self.stage_total_times[stage_idx])
        remaining_str = format_time(remaining)

        # Update stage progress bar
        self.stage_pbars[stage_idx].update(1)  # Update progress first
        self.stage_pbars[stage_idx].set_postfix_str(
            f"{elapsed_str}<{remaining_str} {rate_str} waiting:{waiting}",
            refresh=True
        )

    def update_main_progress(self, num: int) -> None:
        """Update the main progress bar."""
        if self.show_progress and self.progress_bars:
            self.progress_bars[0].update(num)

    def cleanup(self) -> None:
        """Clean up all progress bars."""
        for pbar in self.progress_bars:
            if pbar:
                try:
                    pbar.close()
                except:
                    pass
        self.progress_bars = []
        self.stage_pbars = []
