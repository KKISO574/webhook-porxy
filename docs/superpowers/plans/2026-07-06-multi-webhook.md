# Multi Webhook Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send every generated Enterprise WeChat message to one or more configured robot webhook URLs.

**Architecture:** Add a small configuration parser that resolves delivery targets from `WECHAT_WEBHOOK_URLS` or the legacy `WECHAT_WEBHOOK_URL`. Keep message payload construction unchanged and fan out the same payload to every target inside `send_wechat_message()`.

**Tech Stack:** Python 3, FastAPI, requests, python-dotenv, stdlib unittest.

## Global Constraints

- Preserve compatibility with existing `WECHAT_WEBHOOK_URL`.
- Prefer `WECHAT_WEBHOOK_URLS` when configured.
- Attempt every configured target before raising a failure.
- Do not log full webhook URLs.
- Use stdlib tests; do not add new runtime dependencies.

---

### Task 1: Add Failing Tests

**Files:**
- Create: `tests/test_wechat_webhooks.py`

**Interfaces:**
- Consumes: current `main.py` module import behavior.
- Produces: tests for `WECHAT_WEBHOOK_URLS`, `parse_wechat_webhook_urls()`, and `send_wechat_message()`.

- [ ] **Step 1: Write tests for legacy fallback, multi-target parsing, full fan-out, and partial failure.**
- [ ] **Step 2: Run `venv/bin/python -m unittest tests/test_wechat_webhooks.py -v` and verify the new behavior fails before implementation.**

### Task 2: Implement Multi-Target Delivery

**Files:**
- Modify: `main.py`

**Interfaces:**
- Produces: `parse_wechat_webhook_urls(value: str) -> list[str]`, `WECHAT_WEBHOOK_URLS: list[str]`, and multi-target `send_wechat_message()`.

- [ ] **Step 1: Add parser and load targets from `WECHAT_WEBHOOK_URLS` or `WECHAT_WEBHOOK_URL`.**
- [ ] **Step 2: Update `send_wechat_message()` to post the same payload to every target and raise after collecting failures.**
- [ ] **Step 3: Run the unittest file and verify it passes.**

### Task 3: Update Documentation

**Files:**
- Modify: `.envtemple`
- Modify: `README.md`

**Interfaces:**
- Produces: documented `.env` examples for single and multi-robot delivery.

- [ ] **Step 1: Add `WECHAT_WEBHOOK_URLS` to `.envtemple`.**
- [ ] **Step 2: Update README configuration examples and behavior notes.**
- [ ] **Step 3: Run syntax and unittest verification.**
