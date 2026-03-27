"""Tree-sitter infrastructure: availability detection, parser caching, parsing.

Falls back gracefully when tree-sitter or individual grammar packages
are not installed.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skillgen.models import Language

if TYPE_CHECKING:
    from tree_sitter import Node

logger = logging.getLogger(__name__)

# --- Availability Detection ---

TREE_SITTER_AVAILABLE: bool = False

try:
    from tree_sitter import Language as TSLanguage
    from tree_sitter import Parser

    TREE_SITTER_AVAILABLE = True
except ImportError:
    pass


# Grammar specifications: (cache_key, package_name, factory_function_name).
_GRAMMAR_SPECS: list[tuple[str, str, str]] = [
    ("python", "tree_sitter_python", "language"),
    ("typescript", "tree_sitter_typescript", "language_typescript"),
    ("typescript_tsx", "tree_sitter_typescript", "language_tsx"),
    ("javascript", "tree_sitter_javascript", "language"),
    ("java", "tree_sitter_java", "language"),
    ("go", "tree_sitter_go", "language"),
    ("rust", "tree_sitter_rust", "language"),
    ("cpp", "tree_sitter_cpp", "language"),
]


def _load_grammar(pkg_name: str, func_name: str) -> Any:
    """Import a tree-sitter grammar package and return the TSLanguage, or None."""
    try:
        mod = importlib.import_module(pkg_name)
        return TSLanguage(getattr(mod, func_name)())
    except (ImportError, NameError, AttributeError, OSError):
        return None

# Cache for loaded language objects and parsers.
_language_cache: dict[str, Any] = {}
_parser_cache: dict[str, Any] = {}


# Build lookup from cache_key -> (pkg, func) for lazy loading.
_GRAMMAR_LOOKUP: dict[str, tuple[str, str]] = {
    key: (pkg, fn) for key, pkg, fn in _GRAMMAR_SPECS
}


def _get_ts_language(key: str) -> Any:
    """Get the tree-sitter Language object by cache key, with lazy loading."""
    if not TREE_SITTER_AVAILABLE:
        return None
    if key not in _language_cache:
        spec = _GRAMMAR_LOOKUP.get(key)
        _language_cache[key] = _load_grammar(*spec) if spec else None
    return _language_cache[key]


# --- Public API ---


def is_language_available(lang: Language) -> bool:
    """Check if tree-sitter grammar is installed for the given language."""
    if not TREE_SITTER_AVAILABLE:
        return False
    return _get_ts_language(lang.value) is not None


def get_parser(lang: Language, tsx: bool = False) -> Any:
    """Return a cached Parser for the language, or None if unavailable."""
    if not TREE_SITTER_AVAILABLE:
        return None

    cache_key = f"{lang.value}_tsx" if tsx else lang.value
    if cache_key in _parser_cache:
        return _parser_cache[cache_key]

    ts_lang = _get_ts_language(cache_key)
    if ts_lang is None:
        _parser_cache[cache_key] = None
        return None

    parser = Parser(ts_lang)
    _parser_cache[cache_key] = parser
    return parser


def parse_source(source: str, lang: Language, file_path: Path | None = None) -> Node | None:
    """Parse source text and return the root Node, or None if unavailable."""
    if not TREE_SITTER_AVAILABLE:
        return None

    tsx = file_path is not None and file_path.suffix == ".tsx"
    parser = get_parser(lang, tsx=tsx)
    if parser is None:
        return None

    try:
        tree = parser.parse(source.encode("utf-8"))
        return tree.root_node  # type: ignore[no-any-return]
    except Exception:
        logger.debug("tree-sitter parse failed for %s", file_path or "(unknown)")
        return None


def walk_tree(node: Node, type_name: str) -> list[Node]:
    """Recursively find all descendant nodes matching a type name."""
    results: list[Node] = []
    _walk(node, type_name, results)
    return results


def _walk(node: Node, type_name: str, acc: list[Node]) -> None:
    if node.type == type_name:
        acc.append(node)
    for child in node.children:
        _walk(child, type_name, acc)


def walk_tree_multi(node: Node, type_names: set[str]) -> list[Node]:
    """Recursively find all descendant nodes matching any of the given type names."""
    results: list[Node] = []
    _walk_multi(node, type_names, results)
    return results


def _walk_multi(node: Node, type_names: set[str], acc: list[Node]) -> None:
    if node.type in type_names:
        acc.append(node)
    for child in node.children:
        _walk_multi(child, type_names, acc)


def node_text(node: Node | None) -> str:
    """Extract the text of a node as a decoded string."""
    if node is None:
        return ""
    raw = node.text
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw) if raw is not None else ""


def child_by_field(node: Node, field_name: str) -> Node | None:
    """Get a child node by field name, returning None if missing."""
    return node.child_by_field_name(field_name)
