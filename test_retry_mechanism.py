#!/usr/bin/env python3
"""Test the retry mechanism in bot/retry.py"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import time
import asyncio

# Add current directory to path
sys.path.insert(0, '.')

from bot.retry import (
    retry,
    async_retry,
    retry_with_exponential_backoff,
    is_retryable_http_error,
    create_retry_context,
    API_RETRY_CONTEXT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_INITIAL_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_JITTER,
)


class TestRetryMechanism(unittest.TestCase):
    """Test the retry decorator and utilities"""

    def test_retry_success_on_first_attempt(self):
        """Test that function succeeds on first attempt (no retry needed)"""
        mock_func = Mock(return_value="success")

        @retry(max_retries=3)
        def decorated_func():
            return mock_func()

        result = decorated_func()
        self.assertEqual(result, "success")
        self.assertEqual(mock_func.call_count, 1)

    def test_retry_succeeds_after_failures(self):
        """Test that function retries and eventually succeeds"""
        # Simulate 2 failures then success
        mock_func = Mock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "success"])

        @retry(max_retries=3, retryable_exceptions=(ConnectionError,))
        def decorated_func():
            return mock_func()

        result = decorated_func()
        self.assertEqual(result, "success")
        self.assertEqual(mock_func.call_count, 3)

    def test_retry_exhausted_all_attempts(self):
        """Test that retry gives up after max retries"""
        mock_func = Mock(side_effect=ConnectionError("fail"))

        @retry(max_retries=3, retryable_exceptions=(ConnectionError,))
        def decorated_func():
            return mock_func()

        with self.assertRaises(ConnectionError):
            decorated_func()

        self.assertEqual(mock_func.call_count, 4)  # Initial + 3 retries

    def test_retry_only_on_specific_exceptions(self):
        """Test that retry only occurs for specified exceptions"""
        mock_func = Mock(side_effect=ValueError("not retryable"))

        @retry(max_retries=3, retryable_exceptions=(ConnectionError,))
        def decorated_func():
            return mock_func()

        with self.assertRaises(ValueError):
            decorated_func()

        self.assertEqual(mock_func.call_count, 1)  # No retry for ValueError

    def test_retry_exponential_backoff(self):
        """Test that delays increase exponentially"""
        mock_func = Mock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "success"])
        delays = []

        original_time_sleep = time.sleep
        def mock_sleep(delay):
            delays.append(delay)
            return original_time_sleep(0)  # Don't actually sleep in test

        @retry(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
        def decorated_func():
            return mock_func()

        with patch('time.sleep', mock_sleep):
            result = decorated_func()

        # Should have slept twice (after first and second failures)
        self.assertEqual(len(delays), 2)
        # First delay should be ~1.0 with jitter
        self.assertAlmostEqual(delays[0], 1.0, delta=0.2)  # Allow for jitter
        # Second delay should be ~2.0 (1.0 * 2^1) with jitter
        self.assertAlmostEqual(delays[1], 2.0, delta=0.4)  # Allow for jitter
        self.assertEqual(result, "success")

    def test_retry_max_delay_respected(self):
        """Test that delays don't exceed max_delay"""
        # Need 6 errors: initial call + 5 retries
        mock_func = Mock(side_effect=[ConnectionError("fail")] * 6)
        delays = []

        original_time_sleep = time.sleep
        def mock_sleep(delay):
            delays.append(delay)
            return original_time_sleep(0)

        @retry(max_retries=5, initial_delay=10.0, backoff_factor=2.0, max_delay=15.0)
        def decorated_func():
            return mock_func()

        with patch('time.sleep', mock_sleep):
            with self.assertRaises(ConnectionError):
                decorated_func()

        # Should have 5 delays (after each failed attempt except the last)
        self.assertEqual(len(delays), 5)
        # Check that no delay exceeds max_delay (with jitter allowance)
        for delay in delays:
            self.assertLessEqual(delay, 15.0 * 1.1)  # Allow for jitter

    def test_retry_with_on_retry_callback(self):
        """Test that on_retry callback is called"""
        mock_func = Mock(side_effect=[ConnectionError("fail"), "success"])
        callback_calls = []

        def on_retry(attempt, exc):
            callback_calls.append((attempt, str(exc)))

        @retry(max_retries=3, retryable_exceptions=(ConnectionError,), on_retry=on_retry)
        def decorated_func():
            return mock_func()

        result = decorated_func()

        self.assertEqual(len(callback_calls), 1)
        self.assertEqual(callback_calls[0][0], 1)  # First retry attempt
        self.assertIn("fail", callback_calls[0][1])
        self.assertEqual(result, "success")

    def test_is_retryable_http_error(self):
        """Test HTTP status code classification"""
        self.assertTrue(is_retryable_http_error(429))  # Too many requests
        self.assertTrue(is_retryable_http_error(500))  # Server error
        self.assertTrue(is_retryable_http_error(502))
        self.assertTrue(is_retryable_http_error(503))
        self.assertTrue(is_retryable_http_error(504))

        self.assertFalse(is_retryable_http_error(400))  # Client error
        self.assertFalse(is_retryable_http_error(404))
        self.assertFalse(is_retryable_http_error(200))  # Success

    def test_create_retry_context(self):
        """Test retry context creation"""
        context = create_retry_context(
            max_retries=5,
            initial_delay=2.0,
            max_delay=30.0,
            backoff_factor=3.0,
            jitter=0.2,
            retryable_exceptions=(ConnectionError, TimeoutError),
            retryable_status_codes=[429, 500]
        )

        self.assertEqual(context['max_retries'], 5)
        self.assertEqual(context['initial_delay'], 2.0)
        self.assertEqual(context['max_delay'], 30.0)
        self.assertEqual(context['backoff_factor'], 3.0)
        self.assertEqual(context['jitter'], 0.2)
        self.assertEqual(context['retryable_exceptions'], (ConnectionError, TimeoutError))
        self.assertEqual(context['retryable_status_codes'], [429, 500])

    def test_api_retry_context_defaults(self):
        """Test that API_RETRY_CONTEXT has sensible defaults"""
        self.assertEqual(API_RETRY_CONTEXT['max_retries'], 3)
        self.assertEqual(API_RETRY_CONTEXT['initial_delay'], 1.0)
        self.assertEqual(API_RETRY_CONTEXT['max_delay'], 10.0)
        self.assertEqual(API_RETRY_CONTEXT['backoff_factor'], 2.0)
        self.assertIn(ConnectionError, API_RETRY_CONTEXT['retryable_exceptions'])
        self.assertIn(TimeoutError, API_RETRY_CONTEXT['retryable_exceptions'])
        self.assertIn(429, API_RETRY_CONTEXT['retryable_status_codes'])
        self.assertIn(500, API_RETRY_CONTEXT['retryable_status_codes'])

    def test_retry_with_exponential_backoff_functional(self):
        """Test the functional retry_with_exponential_backoff utility"""
        mock_func = Mock(side_effect=[ConnectionError("fail"), "success"])

        result = retry_with_exponential_backoff(
            lambda: mock_func(),
            max_retries=3,
            retryable_exceptions=(ConnectionError,)
        )

        self.assertEqual(result, "success")
        self.assertEqual(mock_func.call_count, 2)


class TestAsyncRetryMechanism(unittest.IsolatedAsyncioTestCase):
    """Test the async retry decorator"""

    async def test_async_retry_success_on_first_attempt(self):
        """Test that async function succeeds on first attempt"""
        mock_func = AsyncMock(return_value="success")

        @async_retry(max_retries=3)
        async def decorated_func():
            return await mock_func()

        result = await decorated_func()
        self.assertEqual(result, "success")
        self.assertEqual(mock_func.call_count, 1)

    async def test_async_retry_succeeds_after_failures(self):
        """Test that async function retries and eventually succeeds"""
        # Simulate 2 failures then success
        mock_func = AsyncMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "success"])

        @async_retry(max_retries=3, retryable_exceptions=(ConnectionError,))
        async def decorated_func():
            return await mock_func()

        result = await decorated_func()
        self.assertEqual(result, "success")
        self.assertEqual(mock_func.call_count, 3)

    async def test_async_retry_exponential_backoff(self):
        """Test that async retry uses exponential backoff"""
        mock_func = AsyncMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "success"])
        delays = []

        original_asyncio_sleep = asyncio.sleep
        async def mock_sleep(delay):
            delays.append(delay)
            await original_asyncio_sleep(0)  # Don't actually sleep

        @async_retry(max_retries=3, initial_delay=0.1, backoff_factor=2.0)
        async def decorated_func():
            return await mock_func()

        with patch('asyncio.sleep', mock_sleep):
            result = await decorated_func()

        self.assertEqual(len(delays), 2)
        self.assertAlmostEqual(delays[0], 0.1, delta=0.02)  # Allow for jitter
        self.assertAlmostEqual(delays[1], 0.2, delta=0.04)  # Allow for jitter
        self.assertEqual(result, "success")

    async def test_async_retry_with_callback(self):
        """Test that async retry calls on_retry callback"""
        mock_func = AsyncMock(side_effect=[ConnectionError("fail"), "success"])
        callback_calls = []

        def on_retry(attempt, exc):
            callback_calls.append((attempt, str(exc)))

        @async_retry(max_retries=3, retryable_exceptions=(ConnectionError,), on_retry=on_retry)
        async def decorated_func():
            return await mock_func()

        result = await decorated_func()

        self.assertEqual(len(callback_calls), 1)
        self.assertEqual(callback_calls[0][0], 1)  # First retry attempt
        self.assertIn("fail", callback_calls[0][1])
        self.assertEqual(result, "success")


# Mock for AsyncMock if Python version < 3.8
try:
    from unittest.mock import AsyncMock
except ImportError:
    class AsyncMock(Mock):
        async def __call__(self, *args, **kwargs):
            return super().__call__(*args, **kwargs)


if __name__ == '__main__':
    print("Running retry mechanism tests...")
    print("=" * 60)

    # Run sync tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRetryMechanism))
    suite.addTests(loader.loadTestsFromTestCase(TestAsyncRetryMechanism))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("Test Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"  {test}: {traceback.splitlines()[-1]}")

    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  {test}: {traceback.splitlines()[-1]}")

    sys.exit(0 if result.wasSuccessful() else 1)