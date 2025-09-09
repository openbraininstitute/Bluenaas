from __future__ import annotations

from itertools import product
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

from pydantic import BaseModel, model_validator

T = TypeVar("T")
Self = TypeVar("Self", bound="ExpandableModel")


class ExpansionInfo(BaseModel):
    """Information about which fields were expanded during model expansion."""

    expanded_paths: List[str]
    """List of field paths that contributed to the expansion."""

    total_combinations: int
    """Total number of combinations generated."""

    def __str__(self) -> str:
        return f"ExpansionInfo(paths={self.expanded_paths}, combinations={self.total_combinations})"


class Scan(BaseModel, Generic[T]):
    """Represents either a single value or a parameter scan."""

    values: List[T]

    @model_validator(mode="before")
    def wrap_value(cls, v: Any) -> Any:
        # Allow passing a single value directly
        if isinstance(v, dict) and "values" in v:
            values = v["values"]
            if isinstance(values, list) and len(values) == 0:
                raise ValueError("Scan values list cannot be empty")
            return v
        if isinstance(v, list):
            if len(v) == 0:
                raise ValueError("Scan values list cannot be empty")
            return {"values": v}
        return {"values": [v]}

    def expand(self) -> List[T]:
        return self.values

    def __reduce__(self):
        """Make the class pickleable by defining how to reconstruct it."""
        # Use the base Scan class, not the generic instantiation
        return (Scan, (self.values,))

    def __init__(self, values: Optional[List[T]] = None, **data):
        """Custom init to handle direct values parameter."""
        if values is not None:
            data["values"] = values
        super().__init__(**data)


class ExpandableModel(BaseModel):
    """Base class for models that support param scan expansion."""

    def __getattribute__(self, name: str) -> Any:
        """Override attribute access to unwrap Scan values automatically."""
        value = super().__getattribute__(name)
        if isinstance(value, Scan):
            # Return single value if only one, otherwise return the list
            if len(value.values) == 1:
                return value.values[0]
            else:
                return value.values
        return value

    def get_value(self, name: str) -> Any:
        """Get the unwrapped value of a field (auto-unwraps Scan objects)."""
        value = self._get_raw_field(name)
        if isinstance(value, Scan):
            # Return single value if only one, otherwise return the list
            if len(value.values) == 1:
                return value.values[0]
            else:
                return value.values
        return value

    def _get_raw_field(self, name: str) -> Any:
        """Get the raw field value without unwrapping Scan objects."""
        return super().__getattribute__(name)

    def expand(self: Self) -> List[Self]:
        """Expand the model into all parameter combinations with runtime type hints."""
        configs, _ = self.expand_with_info()
        # Add runtime type information to configs
        for config in configs:
            self._annotate_expanded_config(config)
        return configs

    def expand_with_info(self: Self) -> Tuple[List[Self], ExpansionInfo]:
        """
        Expand the model and return both configurations and expansion info.

        Returns:
            Tuple containing:
            - List of expanded model configurations
            - ExpansionInfo with details about which fields were expanded
        """
        expanded_fields: Dict[str, List[Any]] = {}
        expanded_paths: List[str] = []

        # Iterate over actual field values to preserve type information
        for name, value in self.__dict__.items():
            # Use raw field access to get Scan objects for expansion
            raw_value = self._get_raw_field(name)
            expanded_values, field_expanded_paths = _expand_field_with_tracking(raw_value, name)
            expanded_fields[name] = expanded_values
            expanded_paths.extend(field_expanded_paths)

        configs = []
        for combo in product(*expanded_fields.values()):
            kwargs = dict(zip(expanded_fields.keys(), combo))
            # Create config with unwrapped values (no Scan objects)
            config = self.__class__(**kwargs)
            configs.append(config)

        expansion_info = ExpansionInfo(
            expanded_paths=expanded_paths, total_combinations=len(configs)
        )
        return configs, expansion_info

    def _annotate_expanded_config(self, config: Self) -> None:
        """Add runtime type information to expanded config for better typing."""
        # Create a list of items to avoid modifying dict during iteration
        items = list(config.__dict__.items())
        for name, value in items:
            original_field = self._get_raw_field(name)
            if isinstance(original_field, Scan):
                # The config now has the unwrapped value type
                setattr(config, f"__{name}_type", type(value))
                # Store original scan info for debugging
                setattr(config, f"__{name}_was_scan", True)


def _expand_field(value: Any) -> List[Any]:
    if isinstance(value, Scan):
        return value.values  # Return actual values, not Scan objects
    elif isinstance(value, ExpandableModel):
        return value.expand()
    elif isinstance(value, BaseModel):
        # Recursively expand nested BaseModel instances
        nested_expanded = {}
        has_scans = False

        for name, field_value in value.__dict__.items():
            expanded_field = _expand_field(field_value)
            nested_expanded[name] = expanded_field
            if len(expanded_field) > 1:
                has_scans = True

        if has_scans:
            configs = []
            for combo in product(*nested_expanded.values()):
                kwargs = dict(zip(nested_expanded.keys(), combo))
                configs.append(value.__class__(**kwargs))
            return configs
        else:
            return [value]
    elif isinstance(value, list):
        # Check if list contains expandable elements
        expanded_elements = [_expand_field(elem) for elem in value]

        # If any element expands to multiple values, expand the list
        if any(len(expanded) > 1 for expanded in expanded_elements):
            list_combinations = []
            for combo in product(*expanded_elements):
                list_combinations.append(list(combo))
            return list_combinations
        else:
            return [value]
    else:
        # Other values are not expanded
        return [value]


def _expand_field_with_tracking(value: Any, path: str) -> Tuple[List[Any], List[str]]:
    """
    Expand a field and track which paths were expanded.

    Returns:
        Tuple of (expanded_values, expanded_paths)
    """
    if isinstance(value, Scan):
        expanded_paths = [path] if len(value.values) > 1 else []
        return value.values, expanded_paths  # Return actual values, not Scan objects
    elif isinstance(value, ExpandableModel):
        configs, expansion_info = value.expand_with_info()
        # Prefix all expanded paths with current path
        nested_paths = [f"{path}.{p}" for p in expansion_info.expanded_paths]
        return configs, nested_paths
    elif isinstance(value, BaseModel):
        # Recursively expand nested BaseModel instances
        nested_expanded = {}
        all_expanded_paths = []
        has_scans = False

        for name, field_value in value.__dict__.items():
            field_path = f"{path}.{name}"
            expanded_field, field_paths = _expand_field_with_tracking(field_value, field_path)
            nested_expanded[name] = expanded_field
            all_expanded_paths.extend(field_paths)
            if len(expanded_field) > 1:
                has_scans = True

        if has_scans:
            configs = []
            for combo in product(*nested_expanded.values()):
                kwargs = dict(zip(nested_expanded.keys(), combo))
                configs.append(value.__class__(**kwargs))
            return configs, all_expanded_paths
        else:
            return [value], []
    elif isinstance(value, list):
        # Check if list contains expandable elements
        expanded_elements = []
        all_expanded_paths = []

        for i, elem in enumerate(value):
            elem_path = f"{path}[{i}]"
            expanded_elem, elem_paths = _expand_field_with_tracking(elem, elem_path)
            expanded_elements.append(expanded_elem)
            all_expanded_paths.extend(elem_paths)

        # If any element expands to multiple values, expand the list
        if any(len(expanded) > 1 for expanded in expanded_elements):
            list_combinations = []
            for combo in product(*expanded_elements):
                list_combinations.append(list(combo))
            return list_combinations, all_expanded_paths
        else:
            return [value], []
    else:
        # Other values are not expanded
        return [value], []
