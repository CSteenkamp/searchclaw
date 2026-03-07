"""Validate extracted data against a user-provided schema."""

from typing import Any


def _coerce_type(value: Any, expected_type: str) -> tuple[Any, bool]:
    """Try to coerce a value to the expected type. Returns (coerced_value, success)."""
    if value is None:
        return None, True

    if expected_type == "string":
        return str(value), True
    elif expected_type == "number":
        if isinstance(value, (int, float)):
            return value, True
        try:
            return float(value), True
        except (ValueError, TypeError):
            return value, False
    elif expected_type == "boolean":
        if isinstance(value, bool):
            return value, True
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True, True
            if value.lower() in ("false", "0", "no"):
                return False, True
        return value, False
    elif expected_type == "array":
        if isinstance(value, list):
            return value, True
        return value, False
    elif isinstance(expected_type, dict):
        if isinstance(value, dict):
            return validate_against_schema(value, expected_type)
        return value, False

    return value, True


def validate_against_schema(
    data: dict[str, Any], schema: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Validate and coerce extracted data against the user-provided schema."""
    validated: dict[str, Any] = {}
    warnings: list[str] = []

    for key, expected_type in schema.items():
        if key not in data:
            warnings.append(f"Missing field: {key}")
            continue

        value = data[key]

        if isinstance(expected_type, list) and len(expected_type) == 1:
            if not isinstance(value, list):
                warnings.append(f"Field '{key}' expected array, got {type(value).__name__}")
                validated[key] = value
                continue
            item_type = expected_type[0]
            coerced_items = []
            for i, item in enumerate(value):
                coerced, ok = _coerce_type(item, item_type)
                if not ok:
                    warnings.append(f"Field '{key}[{i}]' could not be coerced to {item_type}")
                coerced_items.append(coerced)
            validated[key] = coerced_items
        elif isinstance(expected_type, dict):
            if not isinstance(value, dict):
                warnings.append(f"Field '{key}' expected object, got {type(value).__name__}")
                validated[key] = value
            else:
                nested_data, nested_warnings = validate_against_schema(value, expected_type)
                validated[key] = nested_data
                warnings.extend(f"{key}.{w}" for w in nested_warnings)
        else:
            coerced, ok = _coerce_type(value, expected_type)
            if not ok:
                warnings.append(f"Field '{key}' could not be coerced to {expected_type}")
            validated[key] = coerced

    for key in data:
        if key not in schema:
            validated[key] = data[key]

    return validated, warnings


def build_validation_feedback(warnings: list[str], schema: dict[str, Any]) -> str:
    """Build a feedback prompt for the LLM when validation fails."""
    lines = ["The previous response had validation issues:"]
    for w in warnings:
        lines.append(f"  - {w}")
    lines.append(f"\nPlease return valid JSON matching this schema exactly: {schema}")
    return "\n".join(lines)
