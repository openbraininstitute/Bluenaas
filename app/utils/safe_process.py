import multiprocessing
import traceback
from typing import Any, Callable


class SafeProcessError(Exception):
    logs: str
    """Base exception class for safe process execution errors."""

    def __init__(self, message: str, logs: str = ""):
        super().__init__(message)
        self.logs = logs


class SafeProcessTimeoutError(SafeProcessError):
    """Exception raised when a process times out."""

    pass


class SafeProcessRuntimeError(SafeProcessError):
    """Exception raised when a process fails or exits with non-zero code."""

    pass


class SafeProcessResult:
    """Container for subprocess execution results."""

    def __init__(
        self,
        result: Any = None,
        logs: str = "",
    ):
        self.result = result
        self.logs = logs


def _subprocess_worker(
    target_func: Callable,
    args: tuple,
    kwargs: dict,
    result_queue: multiprocessing.Queue,
):
    """Worker function that runs in the isolated subprocess."""
    try:
        result = target_func(*args, **kwargs)
        result_queue.put(SafeProcessResult(result=result, logs=""))

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        traceback_str = traceback.format_exc()
        result_queue.put(("exception", f"{error_msg}\n{traceback_str}", ""))


class SafeProcessExecutor:
    """
    Executes functions in isolated subprocesses with full error handling.

    This class provides a safe way to run potentially unstable code in separate processes,
    handling failures gracefully through exceptions.

    Features:
    - Process isolation: Code runs in a separate process that cannot crash the main process
    - Timeout support: Processes can be terminated if they run too long
    - Exception safety: Subprocess exceptions are caught and re-raised as custom exceptions
    - Exit code handling: Non-zero exit codes raise exceptions

    Args:
        timeout: Optional timeout in seconds. If None, processes can run indefinitely.

    Returns:
        SafeProcessResult: Contains 'result' attribute on success

    Raises:
        SafeProcessRuntimeError: For subprocess failures, exceptions, or non-zero exit codes
        SafeProcessTimeoutError: For process timeouts

    Examples:
        Basic usage:
        >>> executor = SafeProcessExecutor(timeout=30)
        >>>
        >>> def safe_calculation(x, y):
        ...     return x + y
        >>>
        >>> try:
        ...     result = executor.execute(safe_calculation, 5, 3)
        ...     print(f"Result: {result.result}")  # 8
        ... except SafeProcessRuntimeError as e:
        ...     print(f"Error: {e}")

        Handling failures:
        >>> def failing_function():
        ...     raise ValueError("Something went wrong")
        >>>
        >>> try:
        ...     executor.execute(failing_function)
        ... except SafeProcessRuntimeError as e:
        ...     print(f"Caught: {e}")

        Timeout handling:
        >>> def slow_function():
        ...     import time
        ...     time.sleep(60)  # Will timeout after 30 seconds
        >>>
        >>> try:
        ...     executor.execute(slow_function)
        ... except SafeProcessTimeoutError as e:
        ...     print(f"Timed out: {e}")
    """

    def __init__(self, timeout: float | None = None):
        self.timeout = timeout

    def execute(self, target_func: Callable, *args, **kwargs) -> SafeProcessResult:
        """
        Execute a function in a separate process safely.

        Args:
            target_func: The function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            SafeProcessResult containing result on success

        Raises:
            SafeProcessRuntimeError: If the subprocess fails or exits with non-zero code
            SafeProcessTimeoutError: If the subprocess times out
        """

        # Create queue for communication
        result_queue = multiprocessing.Queue(maxsize=1)

        # Start the subprocess
        process = multiprocessing.Process(
            target=_subprocess_worker, args=(target_func, args, kwargs, result_queue)
        )

        process.start()

        try:
            # Wait for process completion with timeout
            process.join(timeout=self.timeout)

            # Check if process completed successfully
            if process.is_alive():
                # Process timed out
                process.terminate()
                process.join(timeout=5)  # Give it a moment to terminate

                if process.is_alive():
                    process.kill()  # Force kill if still alive
                    process.join()

                raise SafeProcessTimeoutError(f"Process timed out after {self.timeout} seconds", "")

            # Get the result
            if not result_queue.empty():
                try:
                    queue_item = result_queue.get_nowait()
                except Exception:
                    # Queue operation failed, treat as no result
                    queue_item = None

                if queue_item is not None:
                    if isinstance(queue_item, SafeProcessResult):
                        return queue_item
                    elif isinstance(queue_item, tuple) and queue_item[0] == "exception":
                        # Handle exception from subprocess
                        _, error_msg, subprocess_logs = queue_item
                        raise SafeProcessRuntimeError(error_msg, subprocess_logs)

            # Process exited but no result - check exit code
            exit_code = process.exitcode
            if exit_code != 0:
                raise SafeProcessRuntimeError(f"Process exited with non-zero code: {exit_code}", "")

            # Shouldn't reach here, but handle gracefully
            raise SafeProcessRuntimeError("Process completed but no result received", "")

        except Exception as e:
            # Clean up process if still running
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()

            # Re-raise the exception with additional context if needed
            if isinstance(e, SafeProcessError):
                raise  # Re-raise our own exceptions
            else:
                raise SafeProcessRuntimeError(f"Executor error: {str(e)}", "")
