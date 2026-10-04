"""Field-mapping DSL for migration preflight (TK-MIG-F1).

An engineer writes ``mapping.yaml`` (source column → Zoho ``api_name``
plus transforms); the audit checks it against the target metadata and
applies it to sample values. Invalid files fail as config errors that
name the file line (exit 1), never as silent coercion.

Example::

    version: 1
    source: pipedrive
    entities:
      - name: people
        source_kind: persons
        target_module: Contacts
        fields:
          Last_Name: {from: Name, transform: [trim], required: true}
          Email: {from: Email, transform: [trim, casefold], pii: true}
          Phone: {from: Phone, transform: [trim, e164(region=IN)]}
          Lead_Source: {from: Source, transform: [{map: {values: {web: Web}}}] }
        external_id: {field: External_ID__s, from: ID}
        lookups:
          Account_Name: {entity: organizations, via: Organization ID}

Transforms (applied in listed order): ``trim``, ``casefold``,
``e164(region=IN)``, ``date(format=...)``, ``money(currency_col=...)``,
``map(values={...})``, ``concat(fields=[...], sep=" ")``. Each item is
either a string (``trim`` or ``e164(region=IN)``) or a one-key mapping
(``{map: {values: {...}}}``).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from zohokit.core import money as money_core
from zohokit.core import phones as phones_core

#: Transforms the DSL accepts (anything else → config error with a line).
KNOWN_TRANSFORMS = ("trim", "casefold", "e164", "date", "money", "map", "concat")

_TRANSFORM_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\((?P<args>.*)\))?$")
_ARG_SPLIT_RE = re.compile(r",(?=(?:[^'\"]*['\"][^'\"]*['\"])*[^'\"]*$)")


class MappingConfigError(ValueError):
    """A mapping file problem, always carrying its file line (exit 1)."""

    def __init__(self, path: str, line: int, detail: str) -> None:
        super().__init__(f"{path}:{line}: {detail}")
        self.path = path
        self.line = line
        self.detail = detail


class TransformError(ValueError):
    """One value failed one transform (value-free; callers add provenance)."""

    def __init__(self, transform: str, reason: str) -> None:
        super().__init__(f"transform {transform} failed: {reason}")
        self.transform = transform
        self.reason = reason


class TransformSpec(BaseModel):
    """One parsed transform step: name plus validated string-keyed args."""

    model_config = ConfigDict(frozen=True)

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class FieldMapping(BaseModel):
    """One target field: source column, transforms, flags."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_col: str | None = Field(alias="from", default=None)
    transform: list[TransformSpec] = Field(default_factory=list)
    required: bool = False
    pii: bool = False


class ExternalId(BaseModel):
    """Idempotency anchor: target External ID field fed by a source column."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    field: str
    from_col: str = Field(alias="from")


class LookupMapping(BaseModel):
    """A target lookup resolved through another mapped entity."""

    model_config = ConfigDict(frozen=True)

    entity: str
    via: str


class EntityMapping(BaseModel):
    """One source entity (file kind) mapped onto one target module."""

    model_config = ConfigDict(frozen=True)

    name: str
    source_kind: str
    target_module: str
    fields: dict[str, FieldMapping]
    external_id: ExternalId | None = None
    lookups: dict[str, LookupMapping] = Field(default_factory=dict)


class MappingDoc(BaseModel):
    """A whole mapping file (``version: 1`` only, per fail-closed STD-P1)."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1]
    source: str = "generic"
    entities: list[EntityMapping]

    @field_validator("entities")
    @classmethod
    def _unique_entity_names(cls, value: list[EntityMapping]) -> list[EntityMapping]:
        names = [entity.name for entity in value]
        if len(set(names)) != len(names):
            raise ValueError("entity names must be unique")
        return value


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _split_args(text: str) -> list[str]:
    return [part.strip() for part in _ARG_SPLIT_RE.split(text) if part.strip()]


def parse_transform_name(raw: str) -> tuple[str, list[str], dict[str, str]]:
    """Split ``name`` / ``name(positional)`` / ``name(k=v, ...)`` strings.

    Returns ``(name, positional, keyed)``; raises :class:`TransformError`
    (value-free) on bad syntax. Line numbers are attached by the loader.
    """
    match = _TRANSFORM_RE.match(raw.strip())
    if match is None:
        raise TransformError(raw.strip(), "invalid transform syntax")
    name = match.group("name")
    arg_text = match.group("args")
    positional: list[str] = []
    keyed: dict[str, str] = {}
    if arg_text is not None:
        for part in _split_args(arg_text):
            if "=" in part:
                key, _, val = part.partition("=")
                key, val = key.strip(), _unquote(val.strip())
                if not key:
                    raise TransformError(name, "invalid transform argument")
                keyed[key] = val
            else:
                positional.append(_unquote(part))
    return name, positional, keyed


def coerce_transform(raw: Any) -> TransformSpec:
    """Normalize one raw transform item to a :class:`TransformSpec`.

    Accepts the string form (``trim``, ``e164(region=IN)``) and the
    one-key mapping form (``{map: {values: {...}}}``). Unknown names and
    bad argument shapes raise :class:`TransformError`; the loader adds
    the file line.
    """
    if isinstance(raw, str):
        name, positional, keyed = parse_transform_name(raw)
        args: dict[str, Any] = dict(keyed)
    elif isinstance(raw, dict) and len(raw) == 1:
        name, body = next(iter(raw.items()))
        if not isinstance(name, str):
            raise TransformError(str(name), "transform name must be a string")
        positional = []
        args = {}
        if body is not None:
            if not isinstance(body, dict):
                raise TransformError(name, "mapping-form transform needs an argument mapping")
            args = dict(body)
    else:
        raise TransformError(str(raw), "transform must be a string or a one-key mapping")
    if name not in KNOWN_TRANSFORMS:
        raise TransformError(name, f"unknown transform (expected one of {list(KNOWN_TRANSFORMS)})")
    _check_args(name, positional, args)
    if name == "concat" and positional:
        args = {"fields": list(positional), **args}
    if name == "e164" and positional:
        args = {"region": positional[0], **args}
    if name == "date" and positional:
        args = {"format": positional[0], **args}
    if name == "money" and positional:
        args = {"currency_col": positional[0], **args}
    return TransformSpec(name=name, args=args)


def _check_args(name: str, positional: list[str], args: dict[str, Any]) -> None:
    """Reject wrong argument shapes per transform (raises TransformError)."""
    if name in ("trim", "casefold"):
        if positional or args:
            raise TransformError(name, "takes no arguments")
    elif name == "e164":
        if len(positional) > 1 or (args.keys() - {"region"}):
            raise TransformError(name, "expected e164(region=XX)")
        region = args.get("region", positional[0] if positional else None)
        if region is not None and (not isinstance(region, str) or not region.strip()):
            raise TransformError(name, "region must be a non-empty string")
    elif name == "date":
        if len(positional) > 1 or (args.keys() - {"format"}):
            raise TransformError(name, "expected date(format=...)")
    elif name == "money":
        if len(positional) > 1 or (args.keys() - {"currency_col"}):
            raise TransformError(name, "expected money(currency_col=...)")
        column = args.get("currency_col", positional[0] if positional else None)
        if not isinstance(column, str) or not column:
            raise TransformError(name, "money requires currency_col")
    elif name == "map":
        if positional or set(args) != {"values"}:
            raise TransformError(name, "expected map(values={...})")
        if not isinstance(args["values"], dict) or not args["values"]:
            raise TransformError(name, "map values must be a non-empty mapping")
    elif name == "concat":
        if args.keys() - {"fields", "sep"}:
            raise TransformError(name, "expected concat(fields=[...], sep=...)")
        fields = args.get("fields", positional or None)
        if (
            not isinstance(fields, list)
            or not fields
            or not all(isinstance(item, str) for item in fields)
        ):
            raise TransformError(name, "concat requires a non-empty fields list")


def apply_transforms(
    value: str | None, row: dict[str, str], specs: list[TransformSpec]
) -> str | None:
    """Apply *specs* in order; missing input stays missing.

    ``None``/empty input passes through every transform untouched (a
    missing value is a ``required`` question, not a transform failure).
    ``concat`` ignores the input and joins sibling columns instead.
    Raises :class:`TransformError` (value-free) on the first failure.
    """
    current = value
    for spec in specs:
        if spec.name == "concat":
            fields = spec.args.get("fields", [])
            sep = str(spec.args.get("sep", " "))
            current = sep.join(str(row.get(item, "")) for item in fields)
        elif current is None or current == "":
            continue
        elif spec.name == "trim":
            current = current.strip()
        elif spec.name == "casefold":
            current = current.casefold()
        elif spec.name == "e164":
            region = spec.args.get("region")
            try:
                parsed = phones_core.parse(current, default_region=region)
            except phones_core.PhoneError as exc:
                raise TransformError("e164", "unparseable phone number") from exc
            current = parsed.e164
        elif spec.name == "date":
            fmt = spec.args.get("format")
            try:
                if fmt:
                    parsed_dt = datetime.strptime(current.strip(), fmt)
                else:
                    from zohokit.core import time as time_core

                    parsed_dt = time_core.parse(current.strip())
            except (ValueError, time_core.InvalidTimeError) as exc:
                raise TransformError("date", "unparseable date") from exc
            current = parsed_dt.date().isoformat()
        elif spec.name == "money":
            currency_col = spec.args["currency_col"]
            currency = str(row.get(currency_col, "") or "")
            try:
                money_core.validate_currency(currency)
            except money_core.CurrencyError as exc:
                raise TransformError("money", "unknown currency code") from exc
            try:
                amount = money_core.parse(current.strip())
            except money_core.MoneyError as exc:
                raise TransformError("money", "invalid amount") from exc
            # The target currency field takes the normalized number; the
            # currency code itself was validated above.
            current = format(amount, "f")
        elif spec.name == "map":
            values = spec.args["values"]
            if current not in values:
                raise TransformError("map", "value has no entry in values")
            current = str(values[current])
    return current


# --- loading with line numbers -------------------------------------------------


def _descend(node: Any, part: str | int) -> Any | None:
    """Walk one step down a PyYAML compose node; None when absent."""
    import yaml as _yaml

    if isinstance(node, _yaml.MappingNode) and isinstance(part, str):
        for key_node, value_node in node.value:
            if isinstance(key_node, _yaml.ScalarNode) and key_node.value == part:
                return value_node
        return None
    if isinstance(node, _yaml.SequenceNode) and isinstance(part, int):
        items = node.value
        return items[part] if 0 <= part < len(items) else None
    return None


def _line_of(root: Any, path: list[str | int], fallback: int = 1) -> int:
    """File line (1-based) of the node at *path*; *fallback* when missing."""
    node: Any = root
    for part in path:
        child = _descend(node, part)
        if child is None:
            return fallback
        node = child
    mark = getattr(node, "start_mark", None)
    return (mark.line + 1) if mark is not None else fallback


def load_mapping(path: str | Path) -> MappingDoc:
    """Load and validate a mapping file; errors carry the file line.

    YAML syntax problems, schema violations, unknown transforms and bad
    transform arguments all raise :class:`MappingConfigError` as
    ``path:line: detail`` (exit 1 at the CLI).
    """
    text_path = Path(path)
    try:
        text = text_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise MappingConfigError(str(path), 1, f"cannot read mapping file: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        raise MappingConfigError(
            str(path), (line + 1) if isinstance(line, int) else 1, "invalid YAML"
        ) from exc
    if not isinstance(data, dict):
        raise MappingConfigError(str(path), 1, "mapping must be a YAML object")
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:  # pragma: no cover - safe_load already passed
        raise MappingConfigError(str(path), 1, "invalid YAML") from exc
    # Coerce transform items before schema validation so failures carry
    # the item's own file line (pydantic errors cannot point at YAML).
    entities_raw = data.get("entities", [])
    if isinstance(entities_raw, list):
        for index, entity_raw in enumerate(entities_raw):
            fields_raw = entity_raw.get("fields", {}) if isinstance(entity_raw, dict) else {}
            if not isinstance(fields_raw, dict):
                continue
            for target, field_raw in fields_raw.items():
                if not isinstance(field_raw, dict):
                    continue
                raw_items = field_raw.get("transform", [])
                items = raw_items if isinstance(raw_items, list) else [raw_items]
                specs: list[dict[str, Any]] = []
                for item_index, raw in enumerate(items):
                    try:
                        spec = coerce_transform(raw)
                    except TransformError as exc:
                        line = _line_of(
                            root, ["entities", index, "fields", target, "transform", item_index]
                        )
                        raise MappingConfigError(str(path), line, str(exc)) from exc
                    specs.append(spec.model_dump(mode="json"))
                field_raw["transform"] = specs
                has_concat = any(spec["name"] == "concat" for spec in specs)
                if has_concat and field_raw.get("from") is not None:
                    line = _line_of(root, ["entities", index, "fields", target])
                    raise MappingConfigError(
                        str(path), line, "concat reads sibling columns; omit 'from'"
                    ) from None
    try:
        return MappingDoc.model_validate(data)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        loc = [str(step) if isinstance(step, str) else int(step) for step in first.get("loc", ())]
        # Map pydantic field names back to file keys (from_col → from).
        loc = ["from" if step == "from_col" else step for step in loc]
        line = _line_of(root, loc) if loc else 1
        raise MappingConfigError(str(path), line, f"invalid mapping: {first.get('msg')}") from exc


__all__: list[str] = [
    "KNOWN_TRANSFORMS",
    "EntityMapping",
    "ExternalId",
    "FieldMapping",
    "LookupMapping",
    "MappingConfigError",
    "MappingDoc",
    "TransformError",
    "TransformSpec",
    "apply_transforms",
    "coerce_transform",
    "load_mapping",
    "parse_transform_name",
]
