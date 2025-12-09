import unittest
from src.discover_youtubers import discover_youtubers

class TestDiscoverYouTubers(unittest.TestCase):

    def test_discover_youtubers_valid_query(self):
        query = "gaming"
        results = discover_youtubers(query)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        for youtuber in results:
            self.assertIn('name', youtuber)
            self.assertIn('bio', youtuber)
            self.assertIn('channel_link', youtuber)

    def test_discover_youtubers_empty_query(self):
        query = ""
        results = discover_youtubers(query)
        self.assertEqual(results, [])

    def test_discover_youtubers_invalid_query(self):
        query = "nonexistentchannel123456"
        results = discover_youtubers(query)
        self.assertEqual(results, [])

if __name__ == '__main__':
    unittest.main()