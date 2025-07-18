import argparse
import inspect
import os
from types import UnionType
from typing import Dict, Type, TypeVar, Optional, List, Generic, Literal, Tuple, get_origin, get_args, Union

from pydantic import BaseModel
from pydantic.fields import FieldInfo  # noqa

from omnibox_wizard.common.logger import get_logger

try:
    import yaml
except ImportError:
    yaml = None

logger = get_logger(__name__)

_Config = TypeVar("_Config", bound=BaseModel)


def load_from_config_file(config_path: Optional[str] = None) -> Dict[str, str]:
    if yaml is None:
        raise ImportError("Please install pyyaml to use this feature")
    with open(config_path) as f:
        return yaml.safe_load(f)  # noqa


def dict_prefix_filter(prefix: str, data: dict) -> dict:
    return {k[len(prefix):]: v for k, v in data.items() if k.startswith(prefix)}


def parse_value(value: str, cls: Type):
    if cls is bool:
        return value.lower() in ("true", "1", "yes")
    return cls(value)


def get_types(annotation: Type) -> List[Type]:
    if get_origin(annotation) in [Union, UnionType]:
        classes = [cls for cls in get_args(annotation) if cls is not type(None)]
    else:
        classes = [annotation]
    return classes


def parse_annotation(value: str, annotation: Type):
    classes = get_types(annotation)
    for cls in classes:
        try:
            return parse_value(value, cls)
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Cannot parse value '{value}' to any of {classes}")


def dfs(config_model: Type[_Config], env_dict: Dict[str, str]) -> dict:
    result = {}
    for field_name, field_info in config_model.model_fields.items():  # noqa
        filtered_env_dict = dict_prefix_filter(field_name.upper(), env_dict)
        if "" in filtered_env_dict:
            assert len(filtered_env_dict) == 1, f"Conflict name: {field_name}"
            value = filtered_env_dict.pop("")
            result[field_name] = parse_annotation(value, field_info.annotation)
            continue
        if filtered_env_dict:
            assert issubclass(field_info.annotation, BaseModel)
            result[field_name] = dfs(field_info.annotation, dict_prefix_filter("_", filtered_env_dict))
    return result


def load_from_env(config_model: Type[_Config], env_prefix: str) -> Dict[str, str]:
    env_dict: Dict[str, str] = dict_prefix_filter(env_prefix, dict(os.environ))
    if "" in env_dict:
        env_dict.pop("")

    result = dfs(config_model, dict_prefix_filter("_", env_dict))

    return result


def merge_dicts(old: dict, new: dict, *args: List[dict]):
    if len(args) > 0:
        return merge_dicts(merge_dicts(old, new), *args)
    merged = old.copy()
    for key, value in new.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


class Loader(Generic[_Config]):
    def __init__(
            self,
            config_model: Type[_Config],
            env_prefix: str | None = None,
            config_path: str | None = None,
            config_dict: dict | None = None
    ):
        self.config_model: Type[_Config] = config_model
        self.env_prefix: str | None = env_prefix
        self.config_path: str | None = config_path
        self.config_dict: dict | None = config_dict

    def fields(
            self, config_model: Type[_Config] | None = None, prefix: List[str] = None
    ) -> List[Tuple[List[str], FieldInfo]]:
        fields: List[Tuple[List[str], FieldInfo]] = []
        prefix: List[str] = prefix or []
        for key, field_info in config_model.model_fields.items():  # noqa
            if inspect.isclass(field_info.annotation) and issubclass(field_info.annotation, BaseModel):
                fields.extend(self.fields(field_info.annotation, prefix + [key]))
            else:
                fields.append((prefix + [key], field_info))
        return fields

    def keys(self, key_type: Literal["arg", "env"]) -> List[str]:
        assert key_type in ("arg", "env"), f"key_type must be 'arg' or 'env', but got {key_type}"
        assert key_type == "arg" or self.env_prefix is not None, f"env_prefix must be set when key_type is 'env'"
        fields: List[Tuple[List[str], FieldInfo]] = self.fields(self.config_model)
        separator = "-" if key_type == "arg" else "_"
        result: List[str] = []

        for keys, field_info in fields:
            field = separator.join(keys)
            field = ("--" if key_type == "arg" else f"{self.env_prefix}_") + field
            if key_type == "arg":
                field = field.replace("_", "-")
            field = field.lower() if key_type == "arg" else field.upper()
            result.append(field)

        return result

    def load_from_cli(self) -> Dict[str, str]:
        parser = argparse.ArgumentParser()
        for keys, field_info in self.fields(self.config_model):
            name = "-".join(keys).replace("_", "-").lower()
            parser.add_argument(
                f"--{name}",
                dest=name,
                type=get_types(field_info.annotation)[0],
                default=None,
                help=field_info.description,
            )
        args, _ = parser.parse_known_args()
        c = vars(args)
        return {k: v for k, v in c.items() if v is not None}

    def load(
            self,
            env_prefix: str | None = None,
            config_path: str | None = None,
            config_dict: dict | None = None
    ) -> _Config:
        env_prefix = env_prefix or self.env_prefix
        config_path = config_path or self.config_path
        config_dict = config_dict or self.config_dict
        config_merge: dict = config_dict or {}
        if config_path is not None:
            yaml_config: Dict[str, str] = load_from_config_file(config_path)
            logger.debug({"yaml_config": yaml_config})
            config_merge = merge_dicts(config_merge, yaml_config)
        if env_prefix is not None:
            env_config: Dict[str, str] = load_from_env(self.config_model, env_prefix)
            logger.debug({"env_config": env_config})
            config_merge = merge_dicts(config_merge, env_config)
        cli_config: Dict[str, str] = self.load_from_cli()
        logger.debug({"cli_config": cli_config})
        config_merge = merge_dicts(config_merge, cli_config)
        logger.debug({"config_merge": config_merge})
        config = self.config_model.model_validate(config_merge)
        logger.debug({"config_dump": config.model_dump()})
        return config


__all__ = ["Loader"]
