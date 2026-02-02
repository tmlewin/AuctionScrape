"""
Configuration loader for YAML files.

Loads and validates configuration from YAML files into Pydantic models.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from .models import AppConfig, PortalConfig

if TYPE_CHECKING:
    from typing import Any


class ConfigError(Exception):
    """Configuration loading or validation error."""

    def __init__(self, message: str, path: Path | None = None, details: str | None = None):
        self.path = path
        self.details = details
        super().__init__(message)


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dictionary.
    
    Args:
        path: Path to the YAML file
        
    Returns:
        Parsed YAML contents
        
    Raises:
        ConfigError: If file cannot be read or parsed
    """
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}", path=path)
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data is not None else {}
    except yaml.YAMLError as e:
        raise ConfigError(
            f"Invalid YAML in {path}",
            path=path,
            details=str(e),
        ) from e
    except OSError as e:
        raise ConfigError(
            f"Cannot read {path}",
            path=path,
            details=str(e),
        ) from e


def _expand_env_vars(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand environment variables in string values.
    
    Supports ${VAR} and ${VAR:-default} syntax.
    
    Args:
        data: Dictionary with potential env var references
        
    Returns:
        Dictionary with expanded values
    """
    def expand_value(value: Any) -> Any:
        if isinstance(value, str):
            # Handle ${VAR:-default} syntax
            import re
            pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'
            
            def replacer(match: re.Match[str]) -> str:
                var_name = match.group(1)
                default = match.group(2) or ""
                return os.environ.get(var_name, default)
            
            return re.sub(pattern, replacer, value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        return value
    
    return expand_value(data)


def load_app_config(
    path: Path | str | None = None,
    expand_env: bool = True,
) -> AppConfig:
    """Load application configuration from YAML file.
    
    Args:
        path: Path to app.yaml (default: configs/app.yaml)
        expand_env: Whether to expand environment variables
        
    Returns:
        Validated AppConfig instance
        
    Raises:
        ConfigError: If configuration is invalid
    """
    if path is None:
        path = Path("configs/app.yaml")
    else:
        path = Path(path)
    
    # If file doesn't exist, return defaults
    if not path.exists():
        return AppConfig()
    
    data = _load_yaml_file(path)
    
    if expand_env:
        data = _expand_env_vars(data)
    
    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(
            f"Invalid app configuration in {path}",
            path=path,
            details=str(e),
        ) from e


def load_portal_config(
    path: Path | str,
    expand_env: bool = True,
) -> PortalConfig:
    """Load portal configuration from YAML file.
    
    Args:
        path: Path to portal YAML file
        expand_env: Whether to expand environment variables
        
    Returns:
        Validated PortalConfig instance
        
    Raises:
        ConfigError: If configuration is invalid
    """
    path = Path(path)
    data = _load_yaml_file(path)
    
    if expand_env:
        data = _expand_env_vars(data)
    
    try:
        return PortalConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(
            f"Invalid portal configuration in {path}",
            path=path,
            details=str(e),
        ) from e


def load_all_portal_configs(
    portal_dir: Path | str | None = None,
    expand_env: bool = True,
) -> dict[str, PortalConfig]:
    """Load all portal configurations from a directory.
    
    Args:
        portal_dir: Directory containing portal YAML files
                   (default: configs/portals/)
        expand_env: Whether to expand environment variables
        
    Returns:
        Dictionary mapping portal names to their configs
        
    Raises:
        ConfigError: If any configuration is invalid
    """
    if portal_dir is None:
        portal_dir = Path("configs/portals")
    else:
        portal_dir = Path(portal_dir)
    
    if not portal_dir.exists():
        return {}
    
    configs: dict[str, PortalConfig] = {}
    
    for yaml_file in portal_dir.glob("*.yaml"):
        try:
            config = load_portal_config(yaml_file, expand_env=expand_env)
            configs[config.name] = config
        except ConfigError:
            # Re-raise with context
            raise
    
    for yml_file in portal_dir.glob("*.yml"):
        try:
            config = load_portal_config(yml_file, expand_env=expand_env)
            configs[config.name] = config
        except ConfigError:
            raise
    
    return configs


def get_default_config_paths() -> dict[str, Path]:
    """Get default configuration file paths.
    
    Returns:
        Dictionary of config type to default path
    """
    return {
        "app": Path("configs/app.yaml"),
        "portals": Path("configs/portals"),
    }


def validate_portal_config_file(path: Path | str) -> list[str]:
    """Validate a portal configuration file without loading.
    
    Useful for dry-run validation.
    
    Args:
        path: Path to portal YAML file
        
    Returns:
        List of validation error messages (empty if valid)
    """
    path = Path(path)
    errors: list[str] = []
    
    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors
    
    try:
        data = _load_yaml_file(path)
    except ConfigError as e:
        errors.append(str(e))
        return errors
    
    try:
        PortalConfig.model_validate(data)
    except ValidationError as e:
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            errors.append(f"{loc}: {msg}")
    
    return errors
