"""Modeles de texte et expressions pour les workflows : ``{{ expression | filtre }}``.

Les champs des noeuds d'un workflow peuvent contenir des ``{{ ... }}`` : ils sont
remplaces par la valeur des variables (sortie d'un noeud precedent, valeur du geste...).

    {{ lecture.content }}                  sortie du noeud nomme "lecture"
    {{ gesture.value * 10 }}               calcul
    {{ reponse.json.items[0].name | upper }}
    {{ lecture.content | lines | first }}  filtres chaines avec « | »

Les expressions sont evaluees par un interprete restreint (``ast``, liste blanche) :
ni acces aux attributs speciaux, ni import, ni appel de fonction hors liste. Une variable
inconnue vaut ``None`` (texte vide), pour qu'un champ ne plante jamais l'action.
Si un champ ne contient QU'UNE expression, sa valeur garde son type (nombre, liste...).
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from collections.abc import Callable
from typing import Any

__all__ = [
    "TemplateError",
    "eval_expression",
    "find_references",
    "preview",
    "render",
    "truthy",
]

TOKEN = re.compile(r"\{\{(.*?)\}\}", re.S)
MAX_STRING = 1_000_000
MAX_POWER = 64


class TemplateError(ValueError):
    """Expression invalide ; le message est affichable."""


# --------------------------------------------------------------------------
# Evaluation d'expressions
# --------------------------------------------------------------------------

_BIN: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value if value is not None else ""))
    if not match:
        raise TemplateError(f"nombre attendu ({value!r})")
    return float(match.group(0).replace(",", "."))


def _int(value: Any) -> int:
    return int(_num(value))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "int": _int,
    "float": _num,
    "str": _as_text,
    "bool": lambda v: truthy(v),
    "len": lambda v: len(v) if v is not None else 0,
    "min": min,
    "max": max,
    "abs": abs,
    "round": lambda v, n=0: round(_num(v), int(n)) if n else int(round(_num(v))),
    "sum": lambda v: sum(_num(x) for x in v),
    "sorted": sorted,
    "list": list,
    "floor": lambda v: math.floor(_num(v)),
    "ceil": lambda v: math.ceil(_num(v)),
    "sqrt": lambda v: math.sqrt(_num(v)),
}


class _Evaluator:
    def __init__(self, variables: dict[str, Any]):
        self.vars = variables

    def run(self, node: ast.AST) -> Any:  # noqa: C901 (un interpreteur est naturellement un long switch)
        if isinstance(node, ast.Expression):
            return self.run(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("true", "True"):
                return True
            if node.id in ("false", "False"):
                return False
            if node.id in ("null", "None"):
                return None
            return self.vars.get(node.id)
        if isinstance(node, ast.Attribute):
            return self._member(self.run(node.value), node.attr)
        if isinstance(node, ast.Subscript):
            target = self.run(node.value)
            if isinstance(node.slice, ast.Slice):
                lo = self.run(node.slice.lower) if node.slice.lower else None
                hi = self.run(node.slice.upper) if node.slice.upper else None
                return target[lo:hi] if isinstance(target, (str, list)) else None
            return self._member(target, self.run(node.slice))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result: Any = True
                for value in node.values:
                    result = self.run(value)
                    if not truthy(result):
                        return result
                return result
            result = False
            for value in node.values:
                result = self.run(value)
                if truthy(result):
                    return result
            return result
        if isinstance(node, ast.UnaryOp):
            value = self.run(node.operand)
            if isinstance(node.op, ast.Not):
                return not truthy(value)
            if isinstance(node.op, ast.USub):
                return -_num(value)
            if isinstance(node.op, ast.UAdd):
                return _num(value)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.IfExp):
            return self.run(node.body) if truthy(self.run(node.test)) else self.run(node.orelse)
        if isinstance(node, ast.List | ast.Tuple):
            return [self.run(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {self.run(k): self.run(v) for k, v in zip(node.keys, node.values, strict=True) if k is not None}
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise TemplateError("appel de fonction non autorise")
            return FUNCTIONS[node.func.id](*[self.run(a) for a in node.args])
        raise TemplateError(f"syntaxe non autorisee ({type(node).__name__})")

    @staticmethod
    def _member(target: Any, key: Any) -> Any:
        if isinstance(target, dict):
            return target.get(key)
        if isinstance(target, (list, str)) and isinstance(key, (int, float)):
            index = int(key)
            return target[index] if -len(target) <= index < len(target) else None
        if isinstance(target, (list, str)) and key == "length":
            return len(target)
        return None

    def _binop(self, node: ast.BinOp) -> Any:
        left, right = self.run(node.left), self.run(node.right)
        op = _BIN.get(type(node.op))
        if op is None:
            raise TemplateError("operateur non autorise")
        if isinstance(node.op, ast.Add) and (isinstance(left, str) or isinstance(right, str)):
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            # nombre + texte : concatene (comme dans un champ de modele)
            return _as_text(left) + _as_text(right)
        if isinstance(node.op, ast.Mult) and (isinstance(left, str) or isinstance(right, str)):
            text, count = (left, right) if isinstance(left, str) else (right, left)
            if not isinstance(count, (int, float)) or len(text) * abs(int(count)) > MAX_STRING:
                raise TemplateError("repetition de texte trop grande")
            return text * max(0, int(count))
        a, b = _num(left), _num(right)
        if isinstance(node.op, ast.Pow) and abs(b) > MAX_POWER:
            raise TemplateError("exposant trop grand")
        try:
            result = op(a, b)
        except ZeroDivisionError:
            raise TemplateError("division par zero") from None
        return int(result) if isinstance(result, float) and result.is_integer() and abs(result) < 1e15 else result

    def _compare(self, node: ast.Compare) -> bool:
        left = self.run(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.run(comparator)
            if type(op) not in _CMP:
                raise TemplateError("comparaison non autorisee")
            if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                if left is None or right is None:
                    return False  # valeur absente : la comparaison echoue sans erreur
                if not (isinstance(left, str) and isinstance(right, str)):
                    left, right = _num(left), _num(right)
            elif isinstance(op, (ast.Eq, ast.NotEq)) and left is not None and right is not None:
                left, right = _loose(left), _loose(right)
            if isinstance(op, (ast.In, ast.NotIn)) and right is None:
                right = ""
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True


def _loose(value: Any) -> Any:
    """``"3" == 3`` : un nombre ecrit en texte se compare comme un nombre."""
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text) if text and re.fullmatch(r"-?\d+(?:\.\d+)?", text) else value
        except ValueError:
            return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "non", "no", "none", "null")
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(value)


# --------------------------------------------------------------------------
# Filtres
# --------------------------------------------------------------------------


def _lines(value: Any) -> list[str]:
    return [line for line in _as_text(value).splitlines()]


def _first_number(value: Any) -> float | int | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", _as_text(value))
    if not match:
        return None
    number = float(match.group(0).replace(",", "."))
    return int(number) if number.is_integer() else number


def _regex(value: Any, pattern: str, group: int = 0) -> str:
    try:
        match = re.search(str(pattern), _as_text(value))
    except re.error as exc:
        raise TemplateError(f"expression reguliere invalide : {exc}") from None
    if not match:
        return ""
    try:
        return match.group(int(group)) or ""
    except IndexError:
        return ""


def _fromjson(value: Any) -> Any:
    try:
        return json.loads(_as_text(value))
    except ValueError:
        return None


FILTERS: dict[str, Callable[..., Any]] = {
    "upper": lambda v: _as_text(v).upper(),
    "lower": lambda v: _as_text(v).lower(),
    "title": lambda v: _as_text(v).title(),
    "capitalize": lambda v: _as_text(v).capitalize(),
    "trim": lambda v: _as_text(v).strip(),
    "strip": lambda v: _as_text(v).strip(),
    "int": lambda v: _first_number_int(v),
    "float": lambda v: _first_number(v),
    "number": _first_number,
    "round": lambda v, n=0: round(_num(v), int(n)) if int(n) else int(round(_num(v))),
    "abs": lambda v: abs(_num(v)),
    "length": lambda v: len(v) if isinstance(v, (str, list, dict)) else len(_as_text(v)),
    "first": lambda v: (v[0] if v else None) if isinstance(v, (list, str)) else v,
    "last": lambda v: (v[-1] if v else None) if isinstance(v, (list, str)) else v,
    "lines": _lines,
    "split": lambda v, sep=None: _as_text(v).split(sep) if sep else _as_text(v).split(),
    "join": lambda v, sep=",": str(sep).join(_as_text(x) for x in (v if isinstance(v, list) else [v])),
    "json": lambda v: json.dumps(v, ensure_ascii=False),
    "fromjson": _fromjson,
    "default": lambda v, d="": d if v is None or v == "" else v,
    "replace": lambda v, a, b="": _as_text(v).replace(str(a), str(b)),
    "truncate": lambda v, n=80: _as_text(v)[: int(n)],
    "regex": _regex,
    "reverse": lambda v: v[::-1] if isinstance(v, (list, str)) else v,
    "sort": lambda v: sorted(v) if isinstance(v, list) else v,
    "unique": lambda v: list(dict.fromkeys(v)) if isinstance(v, list) else v,
    "string": _as_text,
    "bool": truthy,
    "not": lambda v: not truthy(v),
}


def _first_number_int(value: Any) -> int | None:
    number = _first_number(value)
    return None if number is None else int(number)


def _split_pipes(text: str) -> list[str]:
    """Decoupe sur les ``|`` hors guillemets et hors parentheses."""
    parts, depth, quote, current = [], 0, "", []
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _parse(source: str) -> ast.Expression:
    try:
        return ast.parse(source.strip(), mode="eval")
    except SyntaxError as exc:
        raise TemplateError(f"expression invalide « {source.strip()} » : {exc.msg}") from None


def eval_expression(source: str, variables: dict[str, Any]) -> Any:
    """Evalue ``expression | filtre | filtre(arg)``."""
    if len(source) > 2000:
        raise TemplateError("expression trop longue")
    first, *filters = _split_pipes(source)
    evaluator = _Evaluator(variables)
    value = evaluator.run(_parse(first))
    for raw in filters:
        raw = raw.strip()
        match = re.fullmatch(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?", raw, re.S)
        if not match or match.group(1) not in FILTERS:
            raise TemplateError(f"filtre inconnu : {raw!r}")
        args: list[Any] = []
        if match.group(2) and match.group(2).strip():
            tuple_ast = _parse(f"({match.group(2)},)")
            args = list(evaluator.run(tuple_ast))
        try:
            value = FILTERS[match.group(1)](value, *args)
        except TemplateError:
            raise
        except (TypeError, ValueError, IndexError) as exc:
            raise TemplateError(f"filtre {match.group(1)} : {exc}") from None
    return value


# --------------------------------------------------------------------------
# Rendu
# --------------------------------------------------------------------------


def render(value: Any, variables: dict[str, Any]) -> Any:
    """Remplace les ``{{ ... }}`` dans une valeur (texte, liste, dictionnaire)."""
    if isinstance(value, str):
        if "{{" not in value:
            return value
        tokens = list(TOKEN.finditer(value))
        if len(tokens) == 1 and value.strip() == tokens[0].group(0):
            result = eval_expression(tokens[0].group(1), variables)
            return "" if result is None else result
        return TOKEN.sub(lambda m: _as_text(eval_expression(m.group(1), variables)), value)
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    return value


def find_references(value: Any) -> set[str]:
    """Noms de variables utilises dans les ``{{ }}`` d'une valeur (premier identifiant)."""
    names: set[str] = set()
    if isinstance(value, str):
        for token in TOKEN.finditer(value):
            try:
                tree = _parse(_split_pipes(token.group(1))[0])
            except TemplateError:
                continue
            names.update(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
    elif isinstance(value, list):
        for item in value:
            names |= find_references(item)
    elif isinstance(value, dict):
        for item in value.values():
            names |= find_references(item)
    return names


def preview(value: Any, limit: int = 120) -> str:
    """Texte court pour les journaux et l'historique."""
    text = _as_text(value).replace("\r", " ").replace("\n", " ⏎ ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
