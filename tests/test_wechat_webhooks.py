import importlib
import os
import sys
import unittest
from unittest.mock import patch


class FakeWechatResponse:
    def __init__(self, body=None):
        self.body = body if body is not None else {"errcode": 0}

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def load_main_with_env(**env_overrides):
    env = {
        "WECHAT_WEBHOOK_URL": "",
        "WECHAT_WEBHOOK_URLS": "",
        "CSQAQ_API_TOKEN": "",
        "CSQAQ_INVENTORY_TASKS": "",
        "CSQAQ_INVENTORY_TASK_IDS": "",
    }
    env.update(env_overrides)
    sys.modules.pop("main", None)
    with patch.dict(os.environ, env, clear=False):
        return importlib.import_module("main")


class WechatWebhookConfigTests(unittest.TestCase):
    def test_uses_legacy_single_webhook_url_when_multi_url_env_is_empty(self):
        main = load_main_with_env(WECHAT_WEBHOOK_URL="https://wechat.example/one")

        self.assertEqual(main.WECHAT_WEBHOOK_URLS, ["https://wechat.example/one"])

    def test_parses_multiple_webhook_urls_from_comma_and_newline_separated_env(self):
        main = load_main_with_env(
            WECHAT_WEBHOOK_URL="https://wechat.example/fallback",
            WECHAT_WEBHOOK_URLS=(
                "https://wechat.example/one, https://wechat.example/two\n"
                "https://wechat.example/three"
            ),
        )

        self.assertEqual(
            main.WECHAT_WEBHOOK_URLS,
            [
                "https://wechat.example/one",
                "https://wechat.example/two",
                "https://wechat.example/three",
            ],
        )


class WechatWebhookDeliveryTests(unittest.TestCase):
    def test_sends_same_message_to_every_configured_webhook(self):
        main = load_main_with_env(
            WECHAT_WEBHOOK_URLS="https://wechat.example/one,https://wechat.example/two"
        )

        with patch.object(
            main.requests,
            "post",
            side_effect=[FakeWechatResponse(), FakeWechatResponse()],
        ) as post:
            result = main.send_wechat_message("markdown", "hello")

        self.assertEqual(result["sent"], 2)
        self.assertEqual(
            [call.args[0] for call in post.call_args_list],
            ["https://wechat.example/one", "https://wechat.example/two"],
        )
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["json"], {"msgtype": "markdown", "markdown": {"content": "hello"}})
            self.assertEqual(call.kwargs["timeout"], 10)

    def test_attempts_remaining_webhooks_before_raising_when_one_target_fails(self):
        main = load_main_with_env(
            WECHAT_WEBHOOK_URLS="https://wechat.example/one,https://wechat.example/two"
        )

        with patch.object(
            main.requests,
            "post",
            side_effect=[
                FakeWechatResponse({"errcode": 93000, "errmsg": "robot disabled"}),
                FakeWechatResponse(),
            ],
        ) as post:
            with self.assertRaises(RuntimeError) as raised:
                main.send_wechat_message("markdown", "hello")

        self.assertEqual(post.call_count, 2)
        self.assertIn("1 个企业微信机器人发送失败", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
