"""
📋 GAMEOVER EDITS — Async Render Queue
Ensures only ONE render job runs at a time on the server.
If multiple users submit renders simultaneously, they get queued up
and are processed one by one with live position updates.
"""

import asyncio
import time
from typing import Callable, Awaitable, Optional


class RenderJob:
    def __init__(self, job_id: str, user_id: int, callback: Callable[[], Awaitable[None]]):
        self.job_id    = job_id
        self.user_id   = user_id
        self.callback  = callback
        self.queued_at = time.time()


class RenderQueue:
    def __init__(self):
        self._queue: asyncio.Queue[RenderJob] = asyncio.Queue()
        self._current: Optional[RenderJob]    = None
        self._worker_task: Optional[asyncio.Task] = None
        # List of (user_id, notify_callback) for notifying users their job started
        self._waiting: list[tuple[int, Callable[[], Awaitable[None]]]] = []

    async def start(self):
        """Start the background worker. Call this once in bot.py on startup."""
        self._worker_task = asyncio.create_task(self._worker_loop())
        print("[Queue] ✅ Render queue worker started.")

    async def _worker_loop(self):
        """Continuously dequeue and process render jobs."""
        while True:
            job = await self._queue.get()
            self._current = job

            try:
                print(f"[Queue] ▶ Starting job {job.job_id} for user {job.user_id}")
                await job.callback()
            except Exception as e:
                print(f"[Queue] ❌ Job {job.job_id} failed: {e}")
            finally:
                self._current = None
                self._queue.task_done()
                print(f"[Queue] ✅ Job {job.job_id} complete. Remaining: {self._queue.qsize()}")

    async def submit(
        self,
        job_id: str,
        user_id: int,
        callback: Callable[[], Awaitable[None]],
    ) -> int:
        """
        Add a render job to the queue.
        Returns the queue position (1 = next to run, 2 = after that, etc.)
        """
        job = RenderJob(job_id=job_id, user_id=user_id, callback=callback)
        await self._queue.put(job)
        position = self._queue.qsize()  # Includes the just-added job
        print(f"[Queue] 📥 Job {job_id} queued at position {position}")
        return position

    def is_busy(self) -> bool:
        """True if a render is currently in progress."""
        return self._current is not None

    def queue_size(self) -> int:
        """Number of jobs waiting (not counting the one currently running)."""
        return self._queue.qsize()

    def current_user(self) -> Optional[int]:
        """User ID of whoever is currently rendering, or None."""
        return self._current.user_id if self._current else None


# Global singleton queue instance — imported by all plugins
render_queue = RenderQueue()
