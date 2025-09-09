import pytest
from typing import List, Optional
from pydantic import BaseModel

from app.domains.expandable_model import Scan, ExpandableModel


class TestScan:
    """Test Scan class functionality."""

    def test_scan_single_value(self):
        """Test Scan with single value."""
        scan = Scan[int](values=[42])
        assert scan.expand() == [42]

    def test_scan_multiple_values(self):
        """Test Scan with multiple values."""
        scan = Scan[float](values=[0.1, 0.2, 0.3])
        assert scan.expand() == [0.1, 0.2, 0.3]

    def test_scan_direct_value_wrapping(self):
        """Test Scan wrapping single value directly."""
        scan = Scan[str].model_validate("hello")
        assert scan.expand() == ["hello"]

    def test_scan_list_wrapping(self):
        """Test Scan wrapping list directly."""
        scan = Scan[int].model_validate([1, 2, 3])
        assert scan.expand() == [1, 2, 3]

    def test_scan_dict_format(self):
        """Test Scan with explicit dict format."""
        scan = Scan[bool].model_validate({"values": [True, False]})
        assert scan.expand() == [True, False]

    def test_scan_empty_list_error(self):
        """Test that empty list raises error."""
        with pytest.raises(ValueError, match="Scan values list cannot be empty"):
            Scan[int].model_validate([])

    def test_scan_empty_dict_values_error(self):
        """Test that empty values in dict raises error."""
        with pytest.raises(ValueError, match="Scan values list cannot be empty"):
            Scan[int].model_validate({"values": []})


class TestExpandableModel:
    """Test basic ExpandableModel functionality."""

    def test_no_scans(self):
        """Test model with no scan fields."""

        class SimpleConfig(ExpandableModel):
            name: str = "test"
            value: int = 42

        config = SimpleConfig()
        expanded = config.expand()
        assert len(expanded) == 1
        assert expanded[0].name == "test"
        assert expanded[0].value == 42

    def test_single_scan_field(self):
        """Test model with single scan field."""

        class Config(ExpandableModel):
            rate: Scan[float]
            size: int = 32

        config = Config(rate=Scan[float](values=[0.01, 0.001]))
        expanded = config.expand()
        assert len(expanded) == 2
        assert expanded[0].rate.values == [0.01]
        assert expanded[1].rate.values == [0.001]
        assert all(c.size == 32 for c in expanded)

    def test_multiple_scan_fields(self):
        """Test model with multiple scan fields."""

        class Config(ExpandableModel):
            param_a: Scan[float]
            param_b: Scan[int]
            steps: int = 10

        config = Config(param_a=Scan[float](values=[0.1, 0.01]), param_b=Scan[int](values=[16, 32]))
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2

        # Check all combinations are present
        combinations = [(c.param_a.values[0], c.param_b.values[0]) for c in expanded]
        expected = [(0.1, 16), (0.1, 32), (0.01, 16), (0.01, 32)]
        assert sorted(combinations) == sorted(expected)
        assert all(c.steps == 10 for c in expanded)


class TestNestedModels:
    """Test nested model expansion."""

    def test_nested_expandable_model(self):
        """Test nested ExpandableModel."""

        class InnerConfig(ExpandableModel):
            param1: Scan[int]
            param2: str = "inner"

        class OuterConfig(ExpandableModel):
            inner: InnerConfig
            param3: Scan[str]

        config = OuterConfig(
            inner=InnerConfig(param1=Scan[int](values=[1, 2])), param3=Scan[str](values=["a", "b"])
        )
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2

        # Check combinations
        combinations = [(c.inner.param1.values[0], c.param3.values[0]) for c in expanded]
        expected = [(1, "a"), (1, "b"), (2, "a"), (2, "b")]
        assert sorted(combinations) == sorted(expected)

    def test_nested_regular_basemodel_with_scans(self):
        """Test nested regular BaseModel containing scans."""

        class InnerConfig(BaseModel):
            rate: Scan[float]
            size: int = 32

        class OuterConfig(ExpandableModel):
            inner: InnerConfig
            steps: Scan[int]

        config = OuterConfig(
            inner=InnerConfig(rate=Scan[float](values=[0.01, 0.001])),
            steps=Scan[int](values=[10, 20]),
        )
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2

        # Check nested scans are expanded
        rate_values = [c.inner.rate.values[0] for c in expanded]
        step_values = [c.steps.values[0] for c in expanded]
        assert set(rate_values) == {0.01, 0.001}
        assert set(step_values) == {10, 20}

    def test_deeply_nested_models(self):
        """Test deeply nested models with scans."""

        class Level3(BaseModel):
            param: Scan[int]

        class Level2(BaseModel):
            level3: Level3
            value: str = "level2"

        class Level1(ExpandableModel):
            level2: Level2
            top_param: Scan[str]

        config = Level1(
            level2=Level2(level3=Level3(param=Scan[int](values=[1, 2]))),
            top_param=Scan[str](values=["x", "y"]),
        )
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2

        # Check deep nesting works
        combinations = [(c.level2.level3.param.values[0], c.top_param.values[0]) for c in expanded]
        expected = [(1, "x"), (1, "y"), (2, "x"), (2, "y")]
        assert sorted(combinations) == sorted(expected)


class TestListExpansion:
    """Test list expansion with scans."""

    def test_list_with_scan_models(self):
        """Test list containing models with scans."""

        class Item(BaseModel):
            value: Scan[int]
            name: str = "item"

        class Config(ExpandableModel):
            items: List[Item]
            global_param: int = 100

        config = Config(
            items=[
                Item(value=Scan[int](values=[1, 2])),
                Item(value=Scan[int](values=[3, 4]), name="item2"),
            ]
        )
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2 (each item has 2 values)

        # Check all items are expanded
        for exp_config in expanded:
            assert len(exp_config.items) == 2
            assert all(len(item.value.values) == 1 for item in exp_config.items)

    def test_list_with_mixed_expandable_items(self):
        """Test list with some expandable and some regular items."""

        class ExpandableItem(BaseModel):
            param: Scan[str]

        class RegularItem(BaseModel):
            value: int = 42

        class Config(ExpandableModel):
            mixed_items: List[BaseModel]

        config = Config(
            mixed_items=[ExpandableItem(param=Scan[str](values=["a", "b"])), RegularItem()]
        )
        expanded = config.expand()
        assert len(expanded) == 2  # Only expandable item contributes to expansion

        # Check regular item remains unchanged
        for exp_config in expanded:
            regular_item = exp_config.mixed_items[1]
            assert isinstance(regular_item, RegularItem)
            assert regular_item.value == 42

    def test_list_no_expandable_items(self):
        """Test list with no expandable items."""

        class RegularItem(BaseModel):
            value: int

        class Config(ExpandableModel):
            items: List[RegularItem]

        items = [RegularItem(value=1), RegularItem(value=2)]
        config = Config(items=items)
        expanded = config.expand()
        assert len(expanded) == 1
        assert expanded[0].items == items

    def test_empty_list(self):
        """Test empty list handling."""

        class Config(ExpandableModel):
            items: List[BaseModel] = []
            param: int = 1

        config = Config()
        expanded = config.expand()
        assert len(expanded) == 1
        assert expanded[0].items == []

    def test_list_with_nested_scans(self):
        """Test list with nested models containing scans."""

        class NestedModel(BaseModel):
            inner_param: Scan[float]

        class ItemModel(BaseModel):
            nested: NestedModel
            item_param: Scan[int]

        class Config(ExpandableModel):
            items: List[ItemModel]

        config = Config(
            items=[
                ItemModel(
                    nested=NestedModel(inner_param=Scan[float](values=[0.1, 0.2])),
                    item_param=Scan[int](values=[10, 20]),
                )
            ]
        )
        expanded = config.expand()
        assert len(expanded) == 4  # 2 * 2 (nested_param * item_param)

        # Check all combinations
        combinations = [
            (c.items[0].nested.inner_param.values[0], c.items[0].item_param.values[0])
            for c in expanded
        ]
        expected = [(0.1, 10), (0.1, 20), (0.2, 10), (0.2, 20)]
        assert sorted(combinations) == sorted(expected)


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_complex_scenario(self):
        """Test complex scenario with multiple levels."""

        class Item(BaseModel):
            intensity: Scan[float]
            duration: Scan[int]
            frequency: float = 50.0

        class Group(BaseModel):
            items: List[Item]
            interval: Scan[int]

        class Config(ExpandableModel):
            group: Group
            trials: int = 10

        items = [
            Item(intensity=Scan[float](values=[1.0, 2.0]), duration=Scan[int](values=[100, 200])),
            Item(
                intensity=Scan[float](values=[1.5, 2.5]),
                duration=Scan[int](values=[150, 250]),
                frequency=75.0,
            ),
        ]
        group = Group(items=items, interval=Scan[int](values=[500, 1000]))
        config = Config(group=group)

        expanded = config.expand()
        # 2 intensity * 2 duration * 2 intensity * 2 duration * 2 interval = 32
        assert len(expanded) == 32

        # Check all configs have correct number of items
        for exp in expanded:
            assert len(exp.group.items) == 2
            assert exp.trials == 10

    def test_nested_config_scenario(self):
        """Test nested configuration scenario."""

        class ConfigA(BaseModel):
            type: str = "type_a"
            rate: Scan[float]
            decay: Scan[float]

        class ConfigB(BaseModel):
            layers: List[int] = [128, 64]
            factor: Scan[float]

        class MainConfig(ExpandableModel):
            config_a: ConfigA
            config_b: ConfigB
            size: Scan[int]
            iterations: int = 100

        config = MainConfig(
            config_a=ConfigA(
                rate=Scan[float](values=[0.001, 0.01]),
                decay=Scan[float](values=[1e-4, 1e-5]),
            ),
            config_b=ConfigB(factor=Scan[float](values=[0.1, 0.2, 0.3])),
            size=Scan[int](values=[32, 64]),
        )

        expanded = config.expand()
        # 2 rate * 2 decay * 3 factor * 2 size = 24
        assert len(expanded) == 24

        # Check parameter space coverage
        rate_values = {c.config_a.rate.values[0] for c in expanded}
        factor_values = {c.config_b.factor.values[0] for c in expanded}
        size_values = {c.size.values[0] for c in expanded}

        assert rate_values == {0.001, 0.01}
        assert factor_values == {0.1, 0.2, 0.3}
        assert size_values == {32, 64}


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_scan_with_none_values(self):
        """Test Scan can handle None values."""
        scan = Scan[Optional[int]].model_validate([1, None, 3])
        assert scan.expand() == [1, None, 3]

    def test_very_large_expansion(self):
        """Test handling of large parameter spaces."""

        class Config(ExpandableModel):
            p1: Scan[int]
            p2: Scan[str]

        config = Config(
            p1=Scan[int](values=list(range(10))), p2=Scan[str](values=["a", "b", "c"])
        )  # 10 * 3 = 30
        expanded = config.expand()
        assert len(expanded) == 30

    def test_single_value_scans(self):
        """Test scans with single values don't multiply configs."""

        class Config(ExpandableModel):
            single_scan: Scan[int]
            regular_param: str = "test"

        config = Config(single_scan=Scan[int](values=[42]))
        expanded = config.expand()
        assert len(expanded) == 1
        assert expanded[0].single_scan == 42

    def test_preserve_original_object_attributes(self):
        """Test that expansion preserves all object attributes."""

        class Config(ExpandableModel):
            scan_param: Scan[int]
            regular_param: str = "original"
            list_param: List[str] = ["a", "b"]
            dict_param: dict = {"key": "value"}

        config = Config(scan_param=Scan[int](values=[1, 2]))
        expanded = config.expand()

        for exp_config in expanded:
            assert exp_config.regular_param == "original"
            assert exp_config.list_param == ["a", "b"]
            assert exp_config.dict_param == {"key": "value"}


class TestExpansionTracking:
    """Test expansion tracking functionality."""

    def test_expansion_info_no_scans(self):
        """Test ExpansionInfo with no scan fields."""

        class SimpleConfig(ExpandableModel):
            name: str = "test"
            value: int = 42

        config = SimpleConfig()
        configs, info = config.expand_with_info()

        assert len(configs) == 1
        assert info.total_combinations == 1
        assert info.expanded_paths == []

    def test_expansion_info_single_scan(self):
        """Test ExpansionInfo with single scan field."""

        class Config(ExpandableModel):
            rate: Scan[float]
            size: int = 32

        config = Config(rate=Scan[float](values=[0.01, 0.001]))
        configs, info = config.expand_with_info()

        assert len(configs) == 2
        assert info.total_combinations == 2
        assert info.expanded_paths == ["rate"]

    def test_expansion_info_multiple_scans(self):
        """Test ExpansionInfo with multiple scan fields."""

        class Config(ExpandableModel):
            rate: Scan[float]
            size: Scan[int]
            steps: int = 10

        config = Config(rate=Scan[float](values=[0.1, 0.01]), size=Scan[int](values=[16, 32]))
        configs, info = config.expand_with_info()

        assert len(configs) == 4
        assert info.total_combinations == 4
        assert sorted(info.expanded_paths) == ["rate", "size"]

    def test_expansion_info_nested_scans(self):
        """Test ExpansionInfo with nested scan fields."""

        class InnerConfig(BaseModel):
            rate: Scan[float]
            size: int = 32

        class OuterConfig(ExpandableModel):
            inner: InnerConfig
            steps: Scan[int]

        config = OuterConfig(
            inner=InnerConfig(rate=Scan[float](values=[0.01, 0.001])),
            steps=Scan[int](values=[10, 20]),
        )
        configs, info = config.expand_with_info()

        assert len(configs) == 4
        assert info.total_combinations == 4
        assert sorted(info.expanded_paths) == ["inner.rate", "steps"]

    def test_expansion_info_list_scans(self):
        """Test ExpansionInfo with scans in lists."""

        class Item(BaseModel):
            value: Scan[int]
            name: str = "item"

        class Config(ExpandableModel):
            items: List[Item]
            global_param: int = 100

        config = Config(
            items=[
                Item(value=Scan[int](values=[1, 2])),
                Item(value=Scan[int](values=[3, 4]), name="item2"),
            ]
        )
        configs, info = config.expand_with_info()

        assert len(configs) == 4
        assert info.total_combinations == 4
        assert sorted(info.expanded_paths) == ["items[0].value", "items[1].value"]

    def test_expansion_info_deeply_nested(self):
        """Test ExpansionInfo with deeply nested structures."""

        class Level3(BaseModel):
            param: Scan[int]

        class Level2(BaseModel):
            level3: Level3
            value: str = "level2"

        class Level1(ExpandableModel):
            level2: Level2
            top_param: Scan[str]

        config = Level1(
            level2=Level2(level3=Level3(param=Scan[int](values=[1, 2]))),
            top_param=Scan[str](values=["x", "y"]),
        )
        configs, info = config.expand_with_info()

        assert len(configs) == 4
        assert info.total_combinations == 4
        assert sorted(info.expanded_paths) == ["level2.level3.param", "top_param"]

    def test_expansion_info_single_value_scans(self):
        """Test that single-value scans don't appear in expanded paths."""

        class Config(ExpandableModel):
            single_scan: Scan[int]
            multi_scan: Scan[str]
            regular: int = 42

        config = Config(
            single_scan=Scan[int](values=[1]),  # Single value, shouldn't expand
            multi_scan=Scan[str](values=["a", "b"]),  # Multi value, should expand
        )
        configs, info = config.expand_with_info()

        assert len(configs) == 2
        assert info.total_combinations == 2
        assert info.expanded_paths == ["multi_scan"]

    def test_expansion_info_str_representation(self):
        """Test ExpansionInfo string representation."""

        class Config(ExpandableModel):
            param: Scan[int]

        config = Config(param=Scan[int](values=[1, 2]))
        _, info = config.expand_with_info()

        str_repr = str(info)
        assert "ExpansionInfo" in str_repr
        assert "param" in str_repr
        assert "combinations=2" in str_repr

    def test_backward_compatibility(self):
        """Test that expand() method still works as before."""

        class Config(ExpandableModel):
            rate: Scan[float]
            size: Scan[int]

        config = Config(rate=Scan[float](values=[0.1, 0.01]), size=Scan[int](values=[16, 32]))

        # Test both methods return same configs
        old_configs = config.expand()
        new_configs, _ = config.expand_with_info()

        assert len(old_configs) == len(new_configs) == 4

        # Check they have same combinations
        old_combinations = [(c.rate.values[0], c.size.values[0]) for c in old_configs]
        new_combinations = [(c.rate.values[0], c.size.values[0]) for c in new_configs]
        assert sorted(old_combinations) == sorted(new_combinations)
