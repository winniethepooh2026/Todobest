import pytest
from pydantic import ValidationError

from app.schemas.pages import (
    MAX_EDITOR_DEPTH,
    MAX_EDITOR_NODES,
    PageUpdate,
    validate_editor_document,
)


def test_valid_editor_document() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [{"type": "bold"}],
                    }
                ],
            }
        ],
    }
    assert validate_editor_document(document) == document


def test_current_tiptap_document_schema_is_accepted() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2, "textAlign": "center"},
                "content": [{"type": "text", "text": "Heading"}],
            },
            {
                "type": "paragraph",
                "attrs": {"textAlign": "justify"},
                "content": [
                    {"type": "text", "text": "First line"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Second line"},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Bullet"}],
                            },
                            {
                                "type": "orderedList",
                                "attrs": {"start": -2, "type": "i"},
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {
                                                        "type": "text",
                                                        "text": "Nested item",
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "python"},
                        "content": [{"type": "text", "text": "print('noki')"}],
                    }
                ],
            },
            {"type": "horizontalRule"},
            {
                "type": "image",
                "attrs": {
                    "src": f"/media/images/{'a' * 32}.webp",
                    "alt": "Diagram",
                    "title": None,
                    "width": None,
                    "height": None,
                },
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "attrs": {
                                    "colspan": 2,
                                    "rowspan": 1,
                                    "colwidth": [0, 120],
                                    "align": "center",
                                },
                                "content": [{"type": "paragraph"}],
                            }
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "attrs": {
                                    "colspan": 1,
                                    "rowspan": 1,
                                    "colwidth": None,
                                    "align": None,
                                },
                                "content": [{"type": "paragraph"}],
                            }
                        ],
                    },
                ],
            },
        ],
    }

    assert validate_editor_document(document) == document


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://example.com/docs?q=noki#links", "https://example.com/docs?q=noki#links"),
        ("http://example.com", "http://example.com"),
        ("example.com/docs", "https://example.com/docs"),
        ("//example.com/docs", "https://example.com/docs"),
        ("mailto:team@example.com", "mailto:team@example.com"),
        ("tel:+998901234567", "tel:+998901234567"),
        ("/app/pages/example", "/app/pages/example"),
        ("#section", "#section"),
    ],
)
def test_safe_link_is_accepted_and_normalized(href: str, expected: str) -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": href,
                                    "target": "_blank",
                                    "rel": "noopener noreferrer nofollow",
                                    "class": None,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }

    validated = validate_editor_document(document)

    attrs = validated["content"][0]["content"][0]["marks"][0]["attrs"]
    assert attrs == {
        "href": expected,
        "target": "_blank",
        "rel": "noopener noreferrer nofollow",
    }


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "https://user:password@example.com",
        "https://example.com/bad path",
        "",
        None,
    ],
)
def test_unsafe_link_is_rejected(href: object) -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [{"type": "link", "attrs": {"href": href}}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="Link"):
        validate_editor_document(document)


def test_link_without_attributes_is_rejected() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [{"type": "link"}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="Link attributes"):
        validate_editor_document(document)


def test_external_image_is_rejected() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"src": "https://example.com/private.png"},
            }
        ],
    }
    with pytest.raises(ValueError, match="Only images uploaded"):
        validate_editor_document(document)


@pytest.mark.parametrize(
    "attrs",
    [
        {
            "src": f"/media/images/{'a' * 32}.webp",
            "alt": "x" * 501,
        },
        {
            "src": f"/media/images/{'a' * 32}.webp",
            "style": "position:fixed;inset:0",
        },
        {
            "src": f"/media/images/{'a' * 32}.webp",
            "width": 100,
        },
    ],
)
def test_unsafe_image_rendering_attributes_are_rejected(
    attrs: dict[str, object],
) -> None:
    document = {"type": "doc", "content": [{"type": "image", "attrs": attrs}]}

    with pytest.raises(ValueError, match="Image|attribute|alt"):
        validate_editor_document(document)


def test_unknown_node_is_rejected() -> None:
    document = {"type": "doc", "content": [{"type": "video"}]}
    with pytest.raises(ValueError, match="Unsupported editor node"):
        validate_editor_document(document)


@pytest.mark.parametrize(
    "node",
    [
        {
            "type": "paragraph",
            "attrs": {"textAlign": "left;color:red"},
        },
        {
            "type": "heading",
            "attrs": {"level": 7, "textAlign": None},
        },
        {
            "type": "orderedList",
            "attrs": {"start": 1_000_001},
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph"}],
                }
            ],
        },
        {
            "type": "orderedList",
            "attrs": {"start": 1, "type": "decimal;background:red"},
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph"}],
                }
            ],
        },
        {
            "type": "codeBlock",
            "attrs": {"language": 'python" onclick="alert(1)'},
        },
    ],
)
def test_rendered_node_attributes_are_allowlisted(node: dict[str, object]) -> None:
    document = {"type": "doc", "content": [node]}

    with pytest.raises(ValueError, match="invalid"):
        validate_editor_document(document)


@pytest.mark.parametrize(
    "attrs",
    [
        {"colspan": 0, "rowspan": 1, "colwidth": None},
        {"colspan": 101, "rowspan": 1, "colwidth": None},
        {"colspan": 2, "rowspan": 1, "colwidth": [100]},
        {"colspan": 1, "rowspan": 1, "colwidth": [10_001]},
        {"colspan": 1, "rowspan": 1, "colwidth": None, "align": "justify"},
        {
            "colspan": 1,
            "rowspan": 1,
            "colwidth": None,
            "style": "position:fixed",
        },
    ],
)
def test_table_cell_rendering_attributes_are_bounded(
    attrs: dict[str, object],
) -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "attrs": attrs,
                                "content": [{"type": "paragraph"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="Table|attribute"):
        validate_editor_document(document)


def test_table_effective_column_count_is_bounded() -> None:
    cell = {
        "type": "tableCell",
        "attrs": {"colspan": 51, "rowspan": 1, "colwidth": None},
        "content": [{"type": "paragraph"}],
    }
    document = {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [cell, cell.copy()],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="too many columns"):
        validate_editor_document(document)


@pytest.mark.parametrize(
    "document",
    [
        {"type": "doc", "content": []},
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "paragraph"}],
                }
            ],
        },
        {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [{"type": "paragraph"}],
                }
            ],
        },
        {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "heading",
                                    "attrs": {"level": 2},
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "content": [
                        {
                            "type": "text",
                            "text": "unsafe",
                            "marks": [{"type": "bold"}],
                        }
                    ],
                }
            ],
        },
        {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [{"type": "tableRow", "content": []}],
                }
            ],
        },
    ],
)
def test_editor_node_tree_must_match_tiptap_schema(
    document: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="content|begin|marks"):
        validate_editor_document(document)


def test_unknown_node_property_is_rejected() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "style": "position:fixed",
            }
        ],
    }

    with pytest.raises(ValueError, match="property"):
        validate_editor_document(document)


def test_non_link_mark_attributes_are_rejected() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [{"type": "highlight", "attrs": {"color": "red"}}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="mark attribute"):
        validate_editor_document(document)


def test_editor_document_depth_is_bounded_without_recursion_error() -> None:
    document: dict[str, object] = {"type": "doc"}
    cursor: dict[str, object] = document
    for _ in range(MAX_EDITOR_DEPTH + 1):
        child: dict[str, object] = {"type": "blockquote"}
        cursor["content"] = [child]
        cursor = child
    cursor["content"] = [{"type": "paragraph"}]

    with pytest.raises(ValueError, match="nested too deeply"):
        validate_editor_document(document)


def test_editor_document_node_count_is_bounded() -> None:
    document = {
        "type": "doc",
        "content": [{"type": "paragraph"} for _ in range(MAX_EDITOR_NODES)],
    }

    with pytest.raises(ValueError, match="too many nodes"):
        validate_editor_document(document)


@pytest.mark.parametrize(
    "attrs",
    [
        {"href": "https://example.com", "target": "popup"},
        {"href": "https://example.com", "rel": "opener"},
        {"href": "https://example.com", "rel": 123},
    ],
)
def test_unsafe_link_rendering_attributes_are_rejected(
    attrs: dict[str, object],
) -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Noki",
                        "marks": [{"type": "link", "attrs": attrs}],
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="Link"):
        validate_editor_document(document)


def test_page_update_requires_an_expected_version() -> None:
    with pytest.raises(ValidationError):
        PageUpdate(title="Changed")
