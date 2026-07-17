import time
import gc
import sys

import pytest

@pytest.fixture(autouse=True)
def delay_after_test():
    yield
    # Force garbage collection and a small delay to release any file handles
    gc.collect()
    time.sleep(0.05)
