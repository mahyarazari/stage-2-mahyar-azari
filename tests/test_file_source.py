"""Tests for the checksum-pinned file source (offline: the HTTP client is a stand-in)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from data_factory.exceptions import ChecksumMismatchError
from data_factory.file_source import fetch_files

GOOD = b"a,b\n1,2\n"
DIGEST = hashlib.sha256(GOOD).hexdigest()


class FakeHttp:
    def __init__(self, body):
        self.body, self.urls = body, []

    def get_bytes(self, url):
        self.urls.append(url)
        return self.body


class FileSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_with_the_pinned_checksum_is_not_downloaded_again(self):
        (self.raw / "t.csv").write_bytes(GOOD)
        http = FakeHttp(GOOD)
        result = fetch_files(http, "https://x", {"t.csv": DIGEST}, self.raw)
        self.assertEqual((http.urls, result.reused), ([], ["t.csv"]))

    def test_download_with_the_wrong_bytes_stops_and_writes_nothing(self):
        with self.assertRaises(ChecksumMismatchError):
            fetch_files(FakeHttp(b"a,b\n1,3\n"), "https://x", {"t.csv": DIGEST}, self.raw)
        self.assertEqual(list(self.raw.iterdir()), [])

    def test_damaged_cached_file_is_replaced(self):
        (self.raw / "t.csv").write_bytes(b"half")
        http = FakeHttp(GOOD)
        result = fetch_files(http, "https://x", {"t.csv": DIGEST}, self.raw)
        self.assertEqual((http.urls, result.downloaded), (["https://x/t.csv"], ["t.csv"]))
        self.assertEqual((self.raw / "t.csv").read_bytes(), GOOD)


if __name__ == "__main__":
    unittest.main()
