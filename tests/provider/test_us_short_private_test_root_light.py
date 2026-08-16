from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.provider import us_short_private_test_root_light as helper


class PrivateTestRootLightTests(unittest.TestCase):
    def test_overlap_does_not_remove_parent_before_second_child_is_created(self):
        with TemporaryDirectory() as clean_root:
            root = Path(clean_root)
            original_temporary_directory = helper.tempfile.TemporaryDirectory
            calls = 0
            calls_lock = threading.Lock()
            second_waiting = threading.Event()
            allow_second = threading.Event()
            errors: list[BaseException] = []

            def controlled_temporary_directory(*args, **kwargs):
                nonlocal calls
                with calls_lock:
                    calls += 1
                    call_number = calls
                if call_number == 2:
                    second_waiting.set()
                    if not allow_second.wait(timeout=5):
                        raise RuntimeError("second temporary directory did not resume")
                return original_temporary_directory(*args, **kwargs)

            with patch.object(helper.tempfile, "TemporaryDirectory", controlled_temporary_directory):
                first = helper.temporary_provider_directory(root)
                first.__enter__()

                def second_worker() -> None:
                    try:
                        with helper.temporary_provider_directory(root):
                            pass
                    except BaseException as exc:
                        errors.append(exc)

                thread = threading.Thread(target=second_worker)
                thread.start()
                self.assertTrue(second_waiting.wait(timeout=5))
                first.__exit__(None, None, None)
                self.assertTrue((root / "provider_samples").is_dir())
                allow_second.set()
                thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
