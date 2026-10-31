import unittest
from okam_bridge.transport import response_result


class ResultTests(unittest.TestCase):
    def test_later_failure_overrides_initial_success(self):
        self.assertEqual(response_result(b"result= 0;\r\nresult=-2;\r\n"), -2)

    def test_success(self):
        self.assertEqual(response_result(b"result=0;\r\n"), 0)
