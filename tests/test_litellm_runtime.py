import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import threading
import unittest
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from sift.litellm_proxy import SiftLiteLLMHook
except ImportError:
    SiftLiteLLMHook = None


@unittest.skipIf(SiftLiteLLMHook is None, "install sift-context[litellm] for runtime tests")
class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.005)

    async def call(self, hook, name):
        return await hook._compact(None, {"name": name}, call_type="acompletion", target=700)

    async def assert_busy(self, hook):
        with self.assertRaises(HTTPException) as caught:
            await asyncio.wait_for(self.call(hook, "overload"), 0.25)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers, {"Retry-After": "1"})

    async def test_overload_is_immediate_and_cancelled_running_work_keeps_capacity(self):
        hook = SiftLiteLLMHook({"local": 700})
        gate = threading.Event()
        started = []
        finished = []
        request_id = contextvars.ContextVar("request_id", default="missing")

        def work(router, data, **kwargs):
            started.append((data["name"], request_id.get()))
            try:
                if not gate.wait(3):
                    raise TimeoutError("test worker gate")
                return data
            finally:
                finished.append(data["name"])

        with patch("sift.litellm_proxy.compact_proxy_request", work):
            token = request_id.set("trace-17")
            tasks = [asyncio.create_task(self.call(hook, name)) for name in ("first", "second")]
            request_id.reset(token)
            try:
                await self.wait_for(lambda: len(started) == 2)
                await self.assert_busy(hook)
                tasks[0].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tasks[0]
                await self.assert_busy(hook)
                self.assertEqual({value for _, value in started}, {"trace-17"})
            finally:
                gate.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.wait_for(lambda: len(finished) == 2)
            self.assertEqual((await self.call(hook, "recovery"))["name"], "recovery")
        self.assertEqual({name for name, _ in started}, {"first", "second", "recovery"})

    async def test_cancelled_queued_request_skips_compaction(self):
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        hook = SiftLiteLLMHook({"local": 700})
        gate = threading.Event()
        started = []

        def work(router, data, **kwargs):
            started.append(data["name"])
            if not gate.wait(3):
                raise TimeoutError("test worker gate")
            return data

        with patch("sift.litellm_proxy.compact_proxy_request", work):
            first = asyncio.create_task(self.call(hook, "first"))
            queued = None
            try:
                await self.wait_for(lambda: started == ["first"])
                queued = asyncio.create_task(self.call(hook, "cancelled"))
                await asyncio.sleep(0)
                queued.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await queued
                await self.assert_busy(hook)
            finally:
                gate.set()
                await asyncio.gather(first, *([queued] if queued else []), return_exceptions=True)
            # An executor barrier proves the cancelled queued job has drained.
            await asyncio.get_running_loop().run_in_executor(None, lambda: None)
            self.assertEqual((await self.call(hook, "recovery"))["name"], "recovery")
        self.assertEqual(started, ["first", "recovery"])

    async def test_detached_failure_is_consumed_and_capacity_recovers(self):
        hook = SiftLiteLLMHook({"local": 700})
        gate = threading.Event()
        started = threading.Event()
        loop = asyncio.get_running_loop()
        unhandled = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))

        def work(router, data, **kwargs):
            started.set()
            if not gate.wait(3):
                raise TimeoutError("test worker gate")
            raise ValueError("detached failure")

        try:
            with patch("sift.litellm_proxy.compact_proxy_request", work):
                task = asyncio.create_task(self.call(hook, "cancelled"))
                try:
                    await self.wait_for(started.is_set)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    gate.set()
                    await asyncio.gather(task, return_exceptions=True)
                await loop.shutdown_default_executor()
                await asyncio.sleep(0)
            self.assertEqual(unhandled, [])
        finally:
            loop.set_exception_handler(previous)
        # Submission failure must also give its admission slot back.
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await self.call(hook, "closed-executor")


if __name__ == "__main__":
    unittest.main()
