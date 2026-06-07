from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
from pathlib import PurePath
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

import httpx

from .config import Config


class AutopcrRemoteError(RuntimeError):
    """Raised when the remote autopcr bridge rejects or fails a request."""


_JOB_POLL_INTERVAL_SECONDS = 3.0
_JOB_POLL_TIMEOUT_SECONDS = 3600.0


@dataclass(slots=True)
class RemoteMessage:
    kind: str
    text: str | None = None
    url: str | None = None
    filename: str | None = None
    content: bytes | None = None
    mime_type: str | None = None
    lines: list[str] | None = None
    header: list[str] | None = None
    rows: list[list[str]] | None = None
    result: dict[str, Any] | None = None


@dataclass(slots=True)
class RemoteResult:
    messages: list[RemoteMessage]


class AutopcrRemoteClient:
    def __init__(self, config: Config):
        self.base_url = config.autopcr_api_base_url
        self.public_base_url = config.autopcr_public_base_url
        self.token = config.autopcr_bot_token
        self.timeout = config.autopcr_request_timeout

    def login_url(self) -> str:
        return self.public_base_url + "login"

    def validate_url(self, path: str) -> str:
        return self.public_base_url + path.lstrip("/").removeprefix("daily/")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/plain, image/*, */*"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def health(self) -> RemoteResult:
        return await self._request("GET", "bot/health")

    async def runtime_status(self) -> RemoteResult:
        return await self._request("GET", "bot/runtime/status")

    async def gacha_current(self) -> RemoteResult:
        return await self._request("GET", "bot/gacha/current")

    async def user_info(self, qq: str) -> dict[str, Any]:
        payload = await self._request_json("GET", f"bot/users/{qq}")
        if not isinstance(payload, dict):
            raise AutopcrRemoteError("远端用户信息格式错误")
        return payload

    async def run_daily(self, *, qq: str, alias: str | None, context: dict[str, Any]) -> RemoteResult:
        return await self._request(
            "POST",
            self._account_path(qq, alias, "daily"),
            json={"context": context, "async": True},
        )

    async def run_daily_all(self, *, qq: str, context: dict[str, Any]) -> RemoteResult:
        return await self._request("POST", f"bot/users/{qq}/daily", json={"context": context, "async": True})

    async def daily_records(self, *, qq: str) -> RemoteResult:
        return await self._request("GET", f"bot/users/{qq}/daily-records")

    async def daily_report(self, *, qq: str, alias: str | None, result_id: int) -> RemoteResult:
        return await self._request(
            "GET",
            self._account_path(qq, alias, f"daily-results/{result_id}"),
        )

    async def run_tool(
        self,
        *,
        qq: str,
        alias: str | None,
        tool_name: str,
        tool_key: str,
        config: dict[str, Any],
        export: bool,
        raw_text: str,
        args: list[str],
        context: dict[str, Any],
    ) -> RemoteResult:
        return await self._request(
            "POST",
            self._account_path(qq, alias, f"tools/{tool_key}"),
            json={
                "tool_name": tool_name,
                "tool_key": tool_key,
                "config": config,
                "export": export,
                "raw_text": raw_text,
                "args": args,
                "context": context,
                "async": True,
            },
        )

    async def run_command(
        self,
        *,
        command: str,
        qq: str,
        raw_text: str,
        args: list[str],
        context: dict[str, Any],
    ) -> RemoteResult:
        return await self._request(
            "POST",
            f"bot/users/{qq}/commands/{command}",
            json={"raw_text": raw_text, "args": args, "context": context},
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> RemoteResult:
        response = await self._send(method, path, **kwargs)
        return await self._result_from_response(response)

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._send(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise AutopcrRemoteError("远端返回了无法解析的 JSON") from exc

    async def _wait_for_job(self, job_id: str) -> RemoteResult:
        deadline = time.monotonic() + max(self.timeout, _JOB_POLL_TIMEOUT_SECONDS)
        short_timeout = min(max(self.timeout, 1.0), 30.0)
        while True:
            payload = await self._request_json("GET", f"bot/jobs/{quote(job_id, safe='')}", timeout=short_timeout)
            if not isinstance(payload, dict):
                raise AutopcrRemoteError("远端 job 状态格式错误")

            status = str(payload.get("status") or "")
            if status == "finished":
                response = await self._send(
                    "GET",
                    f"bot/jobs/{quote(job_id, safe='')}/result",
                    timeout=short_timeout,
                )
                return await self._result_from_response(response)
            if status in {"failed", "timeout"}:
                detail = payload.get("error") or status
                raise AutopcrRemoteError(f"远端 autopcr job {status}: {detail}")
            if time.monotonic() >= deadline:
                raise AutopcrRemoteError(f"远端 autopcr job 等待超时: {job_id}")

            await asyncio.sleep(_JOB_POLL_INTERVAL_SECONDS)

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self.base_url + path.lstrip("/")
        timeout = kwargs.pop("timeout", self.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.request(method, url, headers=self._headers(), **kwargs)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text.strip() or exc.response.reason_phrase
                raise AutopcrRemoteError(f"远端 autopcr 返回 {exc.response.status_code}: {detail}") from exc
            except httpx.RequestError as exc:
                raise AutopcrRemoteError(f"无法连接远端 autopcr: {exc}") from exc
        return response

    async def _result_from_response(self, response: httpx.Response) -> RemoteResult:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type.startswith("image/"):
            return RemoteResult([RemoteMessage(kind="image", content=response.content, mime_type=content_type)])
        if content_type in {"application/octet-stream", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
            filename = _filename_from_headers(response.headers) or "autopcr-result"
            return RemoteResult([RemoteMessage(kind="file", filename=filename, content=response.content, mime_type=content_type)])
        if "json" not in content_type:
            text = response.text.strip()
            return RemoteResult([RemoteMessage(kind="text", text=text)] if text else [])

        payload = response.json()
        if response.status_code == 202 and isinstance(payload, dict) and payload.get("job_id"):
            return await self._wait_for_job(str(payload["job_id"]))
        return RemoteResult(_messages_from_payload(payload))

    def _account_path(self, qq: str, alias: str | None, suffix: str) -> str:
        account = quote(alias or "_default", safe="")
        return f"bot/users/{qq}/accounts/{account}/{suffix}"


def _messages_from_payload(payload: Any) -> list[RemoteMessage]:
    if payload is None:
        return []
    if isinstance(payload, str):
        return [RemoteMessage(kind="text", text=payload)] if payload else []
    if isinstance(payload, list):
        return _messages_from_iterable(payload)
    if not isinstance(payload, dict):
        return [RemoteMessage(kind="text", text=str(payload))]
    if payload.get("type") or payload.get("kind"):
        return _messages_from_iterable([payload])

    messages: list[RemoteMessage] = []
    if "messages" in payload:
        messages.extend(_messages_from_iterable(payload["messages"]))
    if payload.get("message"):
        messages.append(RemoteMessage(kind="text", text=str(payload["message"])))
    if payload.get("text"):
        messages.append(RemoteMessage(kind="text", text=str(payload["text"])))
    if payload.get("image"):
        messages.append(_image_message(payload["image"]))
    if payload.get("file"):
        messages.append(_file_message(payload["file"]))
    if payload.get("validate_url"):
        messages.append(RemoteMessage(kind="text", text=f"pcr账号登录需要验证码，请点击以下链接完成认证:\n{payload['validate_url']}"))
    return messages


def _messages_from_iterable(items: Iterable[Any]) -> list[RemoteMessage]:
    messages: list[RemoteMessage] = []
    for item in items:
        if isinstance(item, str):
            messages.append(RemoteMessage(kind="text", text=item))
        elif isinstance(item, dict):
            kind = str(item.get("type") or item.get("kind") or "text")
            if kind == "image":
                messages.append(_image_message(item))
            elif kind == "file":
                messages.append(_file_message(item))
            elif kind == "lines":
                messages.append(_lines_message(item))
            elif kind == "table":
                messages.append(_table_message(item))
            elif kind in {"autopcr_task_result", "autopcr_module_result"}:
                messages.append(_result_message(kind, item))
            else:
                messages.append(RemoteMessage(kind="text", text=str(item.get("text") or item.get("message") or "")))
        else:
            messages.append(RemoteMessage(kind="text", text=str(item)))
    return [
        message
        for message in messages
        if message.text
        or message.url
        or message.content
        or message.lines
        or message.rows
        or message.result is not None
    ]


def _lines_message(data: dict[str, Any]) -> RemoteMessage:
    lines = data.get("lines")
    if isinstance(lines, list):
        return RemoteMessage(kind="lines", lines=[str(line) for line in lines])
    text = data.get("text") or data.get("message") or ""
    return RemoteMessage(kind="lines", lines=str(text).splitlines() or [str(text)])


def _table_message(data: dict[str, Any]) -> RemoteMessage:
    header = data.get("header") or []
    rows = data.get("rows") or []
    return RemoteMessage(
        kind="table",
        header=[str(item) for item in header] if isinstance(header, list) else [str(header)],
        rows=[
            [str(cell) for cell in row]
            for row in rows
            if isinstance(row, list)
        ] if isinstance(rows, list) else [],
    )


def _result_message(kind: str, data: dict[str, Any]) -> RemoteMessage:
    result = data.get("result")
    if isinstance(result, dict):
        return RemoteMessage(kind=kind, result=result)
    return RemoteMessage(kind="text", text="远端返回的 autopcr 结果格式错误")


def _image_message(data: Any) -> RemoteMessage:
    if isinstance(data, str):
        if data.startswith("http://") or data.startswith("https://"):
            return RemoteMessage(kind="image", url=data)
        return RemoteMessage(kind="image", content=_decode_base64(data), mime_type="image/png")
    if isinstance(data, dict):
        content = data.get("content") or data.get("base64")
        return RemoteMessage(
            kind="image",
            url=data.get("url"),
            content=_decode_base64(content) if content else None,
            mime_type=data.get("mime_type") or data.get("content_type"),
        )
    return RemoteMessage(kind="text", text=str(data))


def _file_message(data: Any) -> RemoteMessage:
    if isinstance(data, str):
        return RemoteMessage(kind="file", url=data, filename=_safe_filename(data.rsplit("/", 1)[-1]) or "autopcr-result")
    if isinstance(data, dict):
        content = data.get("content") or data.get("base64")
        return RemoteMessage(
            kind="file",
            url=data.get("url"),
            filename=_safe_filename(data.get("filename") or data.get("name")),
            content=_decode_base64(content) if content else None,
            mime_type=data.get("mime_type") or data.get("content_type"),
        )
    return RemoteMessage(kind="text", text=str(data))


def _decode_base64(value: str) -> bytes:
    if "," in value and value.split(",", 1)[0].startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    disposition = headers.get("content-disposition", "")
    marker = "filename="
    if marker in disposition:
        return _safe_filename(disposition.split(marker, 1)[1].strip().strip('"'))
    content_type = headers.get("content-type", "").split(";", 1)[0].lower()
    extension = mimetypes.guess_extension(content_type)
    return f"autopcr-result{extension}" if extension else None


def _safe_filename(value: str | None) -> str | None:
    if not value:
        return None
    name = PurePath(str(value).replace("\\", "/")).name.strip()
    return name or None
