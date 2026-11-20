"""极简 HTML 正文提取：给格式解析器用的选择器匹配口径。

只依赖标准库，支持正文选择器常用的子集：
- 标签：`p`
- 类：`.closure`、`p.notice`
- 组合：`div.notice > p`（直接子代）、`div.notice p`（后代）
- 分组：`div.notice > p, div.closure p`（逗号分隔，命中任一组即选中）

不支持的选择器写法会在解析阶段抛 ValueError，由调用方转成可读错误。
"""
from __future__ import annotations

from html.parser import HTMLParser


class Node:
    __slots__ = ("tag", "classes", "children", "parent", "text_parts")

    def __init__(self, tag: str, classes: tuple[str, ...], parent: "Node | None") -> None:
        self.tag = tag
        self.classes = classes
        self.children: list[Node] = []
        self.parent = parent
        self.text_parts: list[str] = []

    def text(self) -> str:
        """拼接子树全部文本，块级子元素之间补空格，避免段落黏在一起。"""
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(" ")
            parts.append(child.text())
        return "".join(parts)


class _TreeBuilder(HTMLParser):
    VOID_TAGS = {"br", "hr", "img", "meta", "link", "input"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", (), None)
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = tuple(str(attr_map.get("class") or "").split())
        node = Node(tag.lower(), classes, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag.lower() not in self.VOID_TAGS:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == tag:
                del self._stack[idx:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].text_parts.append(data)


def parse_html(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


class SimpleSelector:
    """链上的一环：标签加可选类名，如 `p.notice`。"""

    __slots__ = ("tag", "cls")

    def __init__(self, tag: str | None, cls: str | None) -> None:
        self.tag = tag
        self.cls = cls

    def matches(self, node: Node) -> bool:
        if self.tag is not None and node.tag != self.tag:
            return False
        if self.cls is not None and self.cls not in node.classes:
            return False
        return True


def _parse_simple(token: str) -> SimpleSelector:
    token = token.strip()
    if not token:
        raise ValueError("选择器里出现空的分段")
    if "." in token:
        tag, _, cls = token.partition(".")
        if not cls or "." in cls:
            raise ValueError(f"暂不支持的类选择器写法：{token}")
        return SimpleSelector(tag.lower() or None, cls)
    if token == "*":
        return SimpleSelector(None, None)
    if not token.isalnum():
        raise ValueError(f"暂不支持的选择器写法：{token}")
    return SimpleSelector(token.lower(), None)


def _parse_group(group: str) -> list[tuple[str, SimpleSelector]]:
    """把一组选择器拆成 (组合符, 简单选择器) 链，组合符是 '>' 或 ' '（后代）。"""
    chain: list[tuple[str, SimpleSelector]] = []
    combinator = " "
    token = ""
    for ch in group.strip():
        if ch == ">":
            if token.strip():
                chain.append((combinator, _parse_simple(token)))
                token = ""
            combinator = ">"
        elif ch.isspace():
            if token.strip():
                chain.append((combinator, _parse_simple(token)))
                token = ""
            combinator = " "
        else:
            token += ch
    if token.strip():
        chain.append((combinator, _parse_simple(token)))
    if not chain:
        raise ValueError("选择器分组为空")
    # 链首的组合符没有意义，统一记成后代。
    chain[0] = (" ", chain[0][1])
    return chain


def _match_chain(node: Node, chain: list[tuple[str, SimpleSelector]]) -> bool:
    combinator, simple = chain[-1]
    if not simple.matches(node):
        return False
    if len(chain) == 1:
        return True
    rest = chain[:-1]
    if combinator == ">":
        return node.parent is not None and _match_chain(node.parent, rest)
    ancestor = node.parent
    while ancestor is not None:
        if _match_chain(ancestor, rest):
            return True
        ancestor = ancestor.parent
    return False


def select(root: Node, selector: str) -> list[Node]:
    """按文档顺序返回命中选择器的元素。"""
    groups = [_parse_group(group) for group in selector.split(",") if group.strip()]
    if not groups:
        raise ValueError("正文选择器为空")
    matched: list[Node] = []

    def walk(node: Node) -> None:
        if node.tag != "#root" and any(_match_chain(node, chain) for chain in groups):
            matched.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    return matched


def extract_paragraphs(html: str, selector: str) -> list[str]:
    """从 HTML 文本里按选择器抽出段落文本，跳过空白段落。"""
    root = parse_html(html)
    paragraphs: list[str] = []
    for node in select(root, selector):
        text = " ".join(node.text().split())
        if text:
            paragraphs.append(text)
    return paragraphs
