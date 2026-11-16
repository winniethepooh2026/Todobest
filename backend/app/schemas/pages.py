from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.schemas.common import UserSummary

EMPTY_DOCUMENT: dict[str, Any] = {"type": "doc", "content": [{"type": "paragraph"}]}

ALLOWED_NODE_TYPES = {
    "doc",
    "paragraph",
    "text",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "hardBreak",
    "image",
    "table",
    "tableRow",
    "tableHeader",
    "tableCell",
}
ALLOWED_MARK_TYPES = {"bold", "italic", "strike", "code", "underline", "highlight", "link"}
LOCAL_IMAGE_PATTERN = re.compile(r"^/media/images/[0-9a-f]{32}\.webp$")
EXPLICIT_PROTOCOL_PATTERN = re.compile(r"^[a-z][a-z\d+.-]*:", re.IGNORECASE)
CODE_LANGUAGE_PATTERN = re.compile(r"^[a-zA-Z0-9_+#.-]{1,64}$")
ALLOWED_LINK_SCHEMES = {"http", "https", "mailto", "tel"}
MAX_LINK_HREF_LENGTH = 2_048
MAX_EDITOR_DEPTH = 100
MAX_EDITOR_NODES = 20_000
MAX_MARKS_PER_NODE = 16
MAX_IMAGE_TEXT_LENGTH = 500
MAX_ORDERED_LIST_START = 1_000_000
MAX_TABLE_SPAN = 100
MAX_TABLE_COLUMNS = 100
MAX_TABLE_COLUMN_WIDTH = 10_000
ALLOWED_LINK_TARGETS = {None, "_blank", "_self"}
ALLOWED_LINK_REL_TOKENS = ("noopener", "noreferrer", "nofollow")
ALLOWED_TEXT_ALIGNMENTS = {None, "left", "center", "right", "justify"}
ALLOWED_TABLE_ALIGNMENTS = {None, "left", "center", "right"}
ALLOWED_ORDERED_LIST_TYPES = {None, "1", "a", "A", "i", "I"}
INLINE_NODE_TYPES = {"text", "hardBreak"}
BLOCK_NODE_TYPES = {
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "image",
    "table",
}
LEAF_NODE_TYPES = {"text", "horizontalRule", "hardBreak", "image"}
NODE_KEYS: dict[str, set[str]] = {
    "doc": {"type", "content"},
    "paragraph": {"type", "attrs", "content"},
    "text": {"type", "text", "marks"},
    "heading": {"type", "attrs", "content"},
    "bulletList": {"type", "content"},
    "orderedList": {"type", "attrs", "content"},
    "listItem": {"type", "content"},
    "blockquote": {"type", "content"},
    "codeBlock": {"type", "attrs", "content"},
    "horizontalRule": {"type"},
    "hardBreak": {"type", "marks"},
    "image": {"type", "attrs"},
    "table": {"type", "content"},
    "tableRow": {"type", "content"},
    "tableHeader": {"type", "attrs", "content"},
    "tableCell": {"type", "attrs", "content"},
}


def normalize_link_href(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Link href must be a string")
    href = value.strip()
    if not href or len(href) > MAX_LINK_HREF_LENGTH:
        raise ValueError("Link href is invalid")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in href
    ):
        raise ValueError("Link href is invalid")

    if href.startswith("#") or (href.startswith("/") and not href.startswith("//")):
        return href
    if href.startswith("//"):
        href = f"https:{href}"
    elif not EXPLICIT_PROTOCOL_PATTERN.match(href):
        href = f"https://{href}"
    if len(href) > MAX_LINK_HREF_LENGTH:
        raise ValueError("Link href is invalid")

    try:
        parsed = urlsplit(href)
        scheme = parsed.scheme.lower()
        if scheme not in ALLOWED_LINK_SCHEMES:
            raise ValueError("Link protocol is not allowed")
        if scheme in {"http", "https"}:
            if not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("Link URL is invalid")
            _ = parsed.port
        elif not parsed.path:
            raise ValueError("Link URL is invalid")
    except ValueError as exc:
        if str(exc).startswith("Link "):
            raise
        raise ValueError("Link URL is invalid") from exc
    return href


def normalize_link_attrs(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Link attributes are required")
    href = normalize_link_href(value.get("href"))

    target = value.get("target")
    if target not in ALLOWED_LINK_TARGETS:
        raise ValueError("Link target is not allowed")

    rel = value.get("rel")
    if rel is not None and not isinstance(rel, str):
        raise ValueError("Link rel is invalid")
    if isinstance(rel, str) and len(rel) > 128:
        raise ValueError("Link rel is invalid")
    rel_tokens = set(rel.split()) if rel else set()
    if not rel_tokens.issubset(ALLOWED_LINK_REL_TOKENS):
        raise ValueError("Link rel is invalid")
    if target == "_blank":
        rel_tokens.update({"noopener", "noreferrer"})

    normalized = {"href": href}
    if target is not None:
        normalized["target"] = target
    canonical_rel = " ".join(token for token in ALLOWED_LINK_REL_TOKENS if token in rel_tokens)
    if canonical_rel:
        normalized["rel"] = canonical_rel
    return normalized


def _node_attrs(
    node: dict[str, Any],
    allowed_keys: set[str],
    *,
    required: bool = False,
) -> dict[str, Any]:
    if "attrs" not in node:
        if required:
            raise ValueError("Editor node attributes are required")
        return {}
    attrs = node["attrs"]
    if not isinstance(attrs, dict):
        raise ValueError("Editor node attributes must be an object")
    if not set(attrs).issubset(allowed_keys):
        raise ValueError("Unsupported editor node attribute")
    return attrs


def _validate_optional_text(
    attrs: dict[str, Any],
    key: str,
    *,
    max_length: int,
) -> None:
    value = attrs.get(key)
    if value is not None and (not isinstance(value, str) or len(value) > max_length):
        raise ValueError(f"Editor node {key} is invalid")


def _validate_integer(
    value: object,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _validate_node_attrs(node: dict[str, Any], node_type: str) -> None:
    if node_type in {"doc", "bulletList", "listItem", "blockquote", "table", "tableRow"}:
        return
    if node_type in {"text", "horizontalRule", "hardBreak"}:
        return

    if node_type == "paragraph":
        attrs = _node_attrs(node, {"textAlign"})
        if attrs.get("textAlign") not in ALLOWED_TEXT_ALIGNMENTS:
            raise ValueError("Paragraph text alignment is invalid")
        return

    if node_type == "heading":
        attrs = _node_attrs(node, {"level", "textAlign"}, required=True)
        _validate_integer(
            attrs.get("level"),
            minimum=1,
            maximum=6,
            label="Heading level",
        )
        if attrs.get("textAlign") not in ALLOWED_TEXT_ALIGNMENTS:
            raise ValueError("Heading text alignment is invalid")
        return

    if node_type == "orderedList":
        attrs = _node_attrs(node, {"start", "type"})
        if "start" in attrs:
            _validate_integer(
                attrs["start"],
                minimum=-MAX_ORDERED_LIST_START,
                maximum=MAX_ORDERED_LIST_START,
                label="Ordered list start",
            )
        if attrs.get("type") not in ALLOWED_ORDERED_LIST_TYPES:
            raise ValueError("Ordered list type is invalid")
        return

    if node_type == "codeBlock":
        attrs = _node_attrs(node, {"language"})
        language = attrs.get("language")
        if language is not None and (
            not isinstance(language, str) or not CODE_LANGUAGE_PATTERN.fullmatch(language)
        ):
            raise ValueError("Code block language is invalid")
        return

    if node_type == "image":
        attrs = _node_attrs(
            node,
            {"src", "alt", "title", "width", "height"},
            required=True,
        )
        src = attrs.get("src")
        if not isinstance(src, str) or not LOCAL_IMAGE_PATTERN.fullmatch(src):
            raise ValueError("Only images uploaded to Noki are allowed")
        _validate_optional_text(attrs, "alt", max_length=MAX_IMAGE_TEXT_LENGTH)
        _validate_optional_text(attrs, "title", max_length=MAX_IMAGE_TEXT_LENGTH)
        if attrs.get("width") is not None or attrs.get("height") is not None:
            raise ValueError("Image dimensions are not supported")
        return

    if node_type in {"tableCell", "tableHeader"}:
        attrs = _node_attrs(node, {"colspan", "rowspan", "colwidth", "align"})
        colspan = _validate_integer(
            attrs.get("colspan", 1),
            minimum=1,
            maximum=MAX_TABLE_SPAN,
            label="Table column span",
        )
        _validate_integer(
            attrs.get("rowspan", 1),
            minimum=1,
            maximum=MAX_TABLE_SPAN,
            label="Table row span",
        )
        if attrs.get("align") not in ALLOWED_TABLE_ALIGNMENTS:
            raise ValueError("Table cell alignment is invalid")
        colwidth = attrs.get("colwidth")
        if colwidth is not None:
            if not isinstance(colwidth, list) or len(colwidth) != colspan:
                raise ValueError("Table column widths are invalid")
            for width in colwidth:
                _validate_integer(
                    width,
                    minimum=0,
                    maximum=MAX_TABLE_COLUMN_WIDTH,
                    label="Table column width",
                )


def _validate_marks(node: dict[str, Any]) -> None:
    if "marks" not in node:
        return
    marks = node["marks"]
    if not isinstance(marks, list):
        raise ValueError("Node marks must be a list")
    if len(marks) > MAX_MARKS_PER_NODE:
        raise ValueError("Node contains too many marks")

    seen_mark_types: set[str] = set()
    for mark in marks:
        if not isinstance(mark, dict) or not set(mark).issubset({"type", "attrs"}):
            raise ValueError("Unsupported editor mark")
        mark_type = mark.get("type")
        if not isinstance(mark_type, str) or mark_type not in ALLOWED_MARK_TYPES:
            raise ValueError("Unsupported editor mark")
        if mark_type in seen_mark_types:
            raise ValueError("Duplicate editor mark")
        seen_mark_types.add(mark_type)
        if mark_type == "link":
            mark["attrs"] = normalize_link_attrs(mark.get("attrs"))
        elif "attrs" in mark and mark["attrs"] not in (None, {}):
            raise ValueError("Unsupported editor mark attribute")


def _node_content(node: dict[str, Any]) -> list[object]:
    if "content" not in node:
        return []
    content = node["content"]
    if not isinstance(content, list):
        raise ValueError("Node content must be a list")
    return content


def _require_child_types(
    children: list[object],
    allowed_types: set[str],
    *,
    minimum: int,
    label: str,
) -> None:
    if len(children) < minimum:
        raise ValueError(f"{label} content is invalid")
    for child in children:
        if not isinstance(child, dict):
            raise ValueError("Every editor node must be an object")
        child_type = child.get("type")
        if child_type not in ALLOWED_NODE_TYPES:
            raise ValueError(f"Unsupported editor node: {child_type}")
        if child_type not in allowed_types:
            raise ValueError(f"{label} content is invalid")


def _validate_node_content(node: dict[str, Any], node_type: str) -> list[object]:
    children = _node_content(node)

    if node_type == "doc":
        _require_child_types(children, BLOCK_NODE_TYPES, minimum=1, label="Document")
    elif node_type in {"paragraph", "heading"}:
        _require_child_types(children, INLINE_NODE_TYPES, minimum=0, label=node_type)
    elif node_type in {"bulletList", "orderedList"}:
        _require_child_types(children, {"listItem"}, minimum=1, label=node_type)
    elif node_type == "listItem":
        _require_child_types(children, BLOCK_NODE_TYPES, minimum=1, label="List item")
        first_child = children[0]
        if not isinstance(first_child, dict) or first_child.get("type") != "paragraph":
            raise ValueError("List item must begin with a paragraph")
    elif node_type == "blockquote":
        _require_child_types(children, BLOCK_NODE_TYPES, minimum=1, label="Blockquote")
    elif node_type == "codeBlock":
        _require_child_types(children, {"text"}, minimum=0, label="Code block")
        if any(isinstance(child, dict) and child.get("marks") for child in children):
            raise ValueError("Code block text cannot have marks")
    elif node_type == "table":
        _require_child_types(children, {"tableRow"}, minimum=1, label="Table")
    elif node_type == "tableRow":
        _require_child_types(
            children,
            {"tableCell", "tableHeader"},
            minimum=1,
            label="Table row",
        )
        effective_columns = 0
        for child in children:
            if not isinstance(child, dict):
                continue
            child_type = child.get("type")
            if child_type not in {"tableCell", "tableHeader"}:
                continue
            _validate_node_attrs(child, child_type)
            attrs = _node_attrs(child, {"colspan", "rowspan", "colwidth", "align"})
            effective_columns += attrs.get("colspan", 1)
            if effective_columns > MAX_TABLE_COLUMNS:
                raise ValueError("Table row contains too many columns")
    elif node_type in {"tableCell", "tableHeader"}:
        _require_child_types(children, BLOCK_NODE_TYPES, minimum=1, label="Table cell")
    elif node_type in LEAF_NODE_TYPES and "content" in node:
        raise ValueError(f"{node_type} cannot contain child nodes")

    return children


def validate_editor_document(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("type") != "doc":
        raise ValueError("Editor document root must be 'doc'")

    total_chars = 0
    node_count = 0
    stack: list[tuple[object, int]] = [(document, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_EDITOR_DEPTH:
            raise ValueError("Editor document is nested too deeply")
        node_count += 1
        if node_count > MAX_EDITOR_NODES:
            raise ValueError("Editor document contains too many nodes")
        if not isinstance(node, dict):
            raise ValueError("Every editor node must be an object")
        node_type = node.get("type")
        if node_type not in ALLOWED_NODE_TYPES:
            raise ValueError(f"Unsupported editor node: {node_type}")
        if not set(node).issubset(NODE_KEYS[node_type]):
            raise ValueError("Unsupported editor node property")

        if node_type == "text":
            text = node.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("Text node value must be a string")
            if len(text) > settings.max_text_node_chars:
                raise ValueError("One text block is too long")
            total_chars += len(text)

        _validate_node_attrs(node, node_type)
        if node_type in INLINE_NODE_TYPES:
            _validate_marks(node)
        children = _validate_node_content(node, node_type)
        stack.extend((child, depth + 1) for child in reversed(children))

    if total_chars > settings.max_page_chars:
        raise ValueError("Page text is too long")
    serialized = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    if len(serialized) > settings.max_page_json_bytes:
        raise ValueError("Editor document is too large")
    return document


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageCreate(StrictRequestModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Page title is required")
        return value


class PageUpdate(StrictRequestModel):
    expected_updated_at: datetime
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: dict[str, Any] | None = None
    markdown: str | None = Field(default=None, max_length=200_000)

    @field_validator("expected_updated_at")
    @classmethod
    def require_version_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Page version must include a timezone")
        return value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if not value:
            raise ValueError("Page title is required")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return validate_editor_document(value) if value is not None else value

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> PageUpdate:
        for field_name in ("title", "content", "markdown"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"Page {field_name} cannot be null")
        return self


class PageOut(BaseModel):
    id: UUID
    team_id: UUID
    title: str
    content: dict[str, Any]
    markdown: str
    created_by: UserSummary
    can_edit: bool
    can_delete: bool
    created_at: datetime
    updated_at: datetime


class PageSummary(BaseModel):
    id: UUID
    team_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class UploadOut(BaseModel):
    id: UUID
    url: str
    width: int
    height: int
    size_bytes: int
