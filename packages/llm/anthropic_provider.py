"""Provider Anthropic — implementação concreta de LLMProvider.

Usado pelo Chief AI (modelo forte via API). Streaming real via SDK.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from packages.llm.base import (
    Completion,
    Message,
    ProviderRequestError,
    StreamChunk,
    ToolCall,
    UnsupportedOperation,
)
from packages.shared.contracts import ToolSpec


def _to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """Converte ToolSpec → formato Anthropic tool_use."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def _to_anthropic_messages(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Separa system prompt e converte Messages → formato Anthropic."""
    system: str | None = None
    api_msgs: list[dict[str, Any]] = []

    for m in messages:
        if m.role == "system":
            system = m.content
            continue

        if m.role == "tool":
            api_msgs.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "",
                            "content": m.content,
                        }
                    ],
                }
            )
            continue

        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["content"] = [
                {"type": "text", "text": m.content} if m.content else None,
                *[
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                    for tc in m.tool_calls
                ],
            ]
            msg["content"] = [c for c in msg["content"] if c is not None]
        api_msgs.append(msg)

    return system, api_msgs


class AnthropicProvider:
    """LLMProvider concreta para API Anthropic. Suporta complete, stream e NÃO embed."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self.name: str = "anthropic"
        self.model: str = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        sys_from_msgs, api_msgs = _to_anthropic_messages(messages)
        effective_system = system or sys_from_msgs

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if effective_system:
            kwargs["system"] = effective_system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            raise ProviderRequestError(
                str(exc), status_code=getattr(exc, "status_code", None)
            ) from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=resp.model,
            finish_reason=resp.stop_reason or "",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        sys_from_msgs, api_msgs = _to_anthropic_messages(messages)
        effective_system = system or sys_from_msgs

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_msgs,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if effective_system:
            kwargs["system"] = effective_system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        try:
            current_tool_id = ""
            current_tool_name = ""
            current_tool_input = ""

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if (
                            hasattr(event.content_block, "type")
                            and event.content_block.type == "tool_use"
                        ):
                            current_tool_id = event.content_block.id
                            current_tool_name = event.content_block.name
                            current_tool_input = ""
                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield StreamChunk(type="text", text=event.delta.text)
                        elif hasattr(event.delta, "partial_json"):
                            current_tool_input += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool_name:
                            try:
                                args = (
                                    json.loads(current_tool_input)
                                    if current_tool_input
                                    else {}
                                )
                            except json.JSONDecodeError:
                                args = {}
                            yield StreamChunk(
                                type="tool_call",
                                tool_call=ToolCall(
                                    id=current_tool_id,
                                    name=current_tool_name,
                                    arguments=args,
                                ),
                            )
                            current_tool_name = ""
                            current_tool_input = ""
                    elif event.type == "message_stop":
                        final = await stream.get_final_message()
                        text_parts = [b.text for b in final.content if b.type == "text"]
                        tc_list = [
                            ToolCall(
                                id=b.id,
                                name=b.name,
                                arguments=b.input if isinstance(b.input, dict) else {},
                            )
                            for b in final.content
                            if b.type == "tool_use"
                        ]
                        yield StreamChunk(
                            type="done",
                            completion=Completion(
                                text="".join(text_parts),
                                tool_calls=tc_list,
                                input_tokens=final.usage.input_tokens,
                                output_tokens=final.usage.output_tokens,
                                model=final.model,
                                finish_reason=final.stop_reason or "",
                            ),
                        )
        except anthropic.APIError as exc:
            yield StreamChunk(type="error", error=str(exc))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise UnsupportedOperation("Anthropic não suporta embeddings")


__all__ = ["AnthropicProvider"]
