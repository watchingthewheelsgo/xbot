import functools
import inspect

from loguru import logger


def safe_func_wrapper(func):
    """
    A decorator that logs function entry, exit, and exceptions.

    Features:
    - Prints function name and parameters before execution
    - Catches exceptions, prints error info, and re-raises
    - Prints success message after successful execution
    - Preserves function metadata and return values
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get function name
        func_name = func.__name__

        # Build parameter dictionary
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        params = dict(bound_args.arguments)

        # Entry log
        logger.info(f"Entering {func_name} with params: {params}")

        try:
            # Execute the function
            result = func(*args, **kwargs)
            # Success log
            logger.info("Success. Exiting..")
            return result
        except Exception as e:
            # Exception log and re-raise
            logger.info(f"Exception: {type(e).__name__}: {e}")
            raise RuntimeError(f"Exception: {type(e).__name__}: {e}")

    return wrapper
