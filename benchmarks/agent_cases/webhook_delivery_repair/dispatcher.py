"""Webhook delivery starter. Repair this module to satisfy docs/delivery_policy.md."""

import json


class Dispatcher:
    def __init__(self, config, sender):
        self.config = config
        self.sender = sender
        self.delivered = set()

    def deliver(self, tenant_id, event_id, payload, now):
        # Starter implementation has several known reliability defects.
        key = event_id
        if key in self.delivered:
            return {
                "state": "duplicate",
                "attempts": 0,
                "duplicate": True,
                "next_attempt_at": None,
                "signature": None,
            }

        endpoint = self.config["primary"]
        body = json.dumps(payload).encode("utf-8")
        response = self.sender(endpoint["url"], body, {})
        if response.status_code:
            self.delivered.add(key)
            return {
                "state": "delivered",
                "attempts": 1,
                "duplicate": False,
                "next_attempt_at": None,
                "signature": None,
            }

        return {
            "state": "retry",
            "attempts": 1,
            "duplicate": False,
            "next_attempt_at": now,
            "signature": None,
        }
