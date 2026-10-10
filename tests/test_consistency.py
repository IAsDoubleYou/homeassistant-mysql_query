"""Checks that the files describing the integration agree with the code.

Home Assistant shows the strings and services.yaml to the user, and nothing
fails when they drift from the code, so these tests do.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import voluptuous as vol
import yaml

from custom_components.mysql_query.__init__ import EXECUTE_SCHEMA, QUERY_SCHEMA
from custom_components.mysql_query.config_flow import (
    get_connection_schema,
    get_options_schema,
)
from custom_components.mysql_query.const import (
    CONF_MYSQL_CHARSET,
    CONF_MYSQL_COLLATION,
    CONF_MYSQL_DB,
    CONF_MYSQL_HOST,
    CONF_MYSQL_PASSWORD,
    CONF_MYSQL_PORT,
    CONF_MYSQL_TIMEOUT,
    CONF_MYSQL_USERNAME,
    CONF_USE_TLS,
    OPTION_KEYS,
    SERVICE_EXECUTE,
    SERVICE_QUERY,
)

PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "mysql_query"
STRINGS = json.loads((PACKAGE / "strings.json").read_text())
EN = json.loads((PACKAGE / "translations" / "en.json").read_text())
NL = json.loads((PACKAGE / "translations" / "nl.json").read_text())
SERVICES = yaml.safe_load((PACKAGE / "services.yaml").read_text())
SOURCE = {path.name: path.read_text() for path in PACKAGE.glob("*.py")}

SCHEMAS = {SERVICE_QUERY: QUERY_SCHEMA, SERVICE_EXECUTE: EXECUTE_SCHEMA}


def _paths(node: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Return the path of every leaf of a nested dict."""
    if isinstance(node, dict):
        return {p for key, value in node.items() for p in _paths(value, (*prefix, key))}
    return {prefix}


def test_english_translation_is_the_strings_file() -> None:
    """en.json is a copy of strings.json."""
    assert EN == STRINGS


def test_dutch_translation_has_exactly_the_keys_of_the_english_one() -> None:
    """No missing and no leftover key in nl.json."""
    assert _paths(NL) == _paths(EN)


def test_every_exception_key_in_the_code_exists_and_every_key_is_used() -> None:
    """Each translation_key is defined, and none is defined for nothing."""
    used = set()
    for text in SOURCE.values():
        used |= set(re.findall(r'translation_key="([a-z_]+)"', text))

    assert used == set(STRINGS["exceptions"])


def test_every_form_error_key_is_defined_and_used() -> None:
    """The errors a form can show are the ones the strings define."""
    used = set(re.findall(r'return "([a-z_]+)", ', SOURCE["config_flow.py"]))

    assert used == set(STRINGS["config"]["error"])


def test_every_abort_reason_is_defined_and_used() -> None:
    """The reasons come from the flow and from Home Assistant's own helpers.

    already_configured comes from the unique_id check, and the two successful
    reasons from async_update_reload_and_abort.
    """
    flow = SOURCE["config_flow.py"]
    used = set(re.findall(r'reason="([a-z_]+)"', flow))
    used |= {"already_configured", "reauth_successful", "reconfigure_successful"}

    assert used == set(STRINGS["config"]["abort"])


def test_every_step_is_defined_and_used() -> None:
    """The steps in the strings are the ones the flows can show."""
    steps = set(re.findall(r'step_id="([a-z_]+)"', SOURCE["config_flow.py"]))

    assert steps == set(STRINGS["config"]["step"]) | set(STRINGS["options"]["step"])


def test_services_are_the_ones_that_are_registered() -> None:
    """services.yaml, the strings and the code name the same actions."""
    assert set(SERVICES) == set(STRINGS["services"]) == set(SCHEMAS)


def test_service_fields_match_the_schema_one_to_one() -> None:
    """services.yaml has the fields of the schema, with its required and default."""
    for service, schema in SCHEMAS.items():
        fields = SERVICES[service]["fields"]
        keys = {str(key): key for key in schema.schema}

        assert set(fields) == set(keys)
        for name, field in fields.items():
            key = keys[name]
            assert field.get("required", False) is isinstance(key, vol.Required), (
                service,
                name,
            )
            if key.default is vol.UNDEFINED:
                assert "default" not in field, (service, name)
            else:
                assert field["default"] == key.default(), (service, name)


def test_service_texts_agree_between_services_yaml_and_the_strings() -> None:
    """The same name and description wherever they are written."""
    for service, spec in SERVICES.items():
        text = STRINGS["services"][service]
        assert spec["name"] == text["name"], service
        assert " ".join(spec["description"].split()) == text["description"], service
        for name, field in spec["fields"].items():
            expected = text["fields"][name]
            assert field["name"] == expected["name"], (service, name)
            assert field["description"] == expected["description"], (service, name)


def _readme_settings() -> dict[str, str]:
    """Return the settings table of the README as {key: where it is changed}."""
    readme = (PACKAGE.parent.parent / "README.md").read_text()
    rows = re.findall(
        r"^\| \*\*[^|]+\*\* \| ```(mysql_[a-z_]+)``` \| (Reconfigure|Configure) \|",
        readme,
        re.MULTILINE,
    )
    return dict(rows)


def test_readme_documents_every_setting_where_it_can_be_changed() -> None:
    """Each setting is in the README table, and under the form that holds it."""
    settings = _readme_settings()

    assert set(settings) == {
        CONF_MYSQL_HOST,
        CONF_MYSQL_PORT,
        CONF_MYSQL_USERNAME,
        CONF_MYSQL_PASSWORD,
        CONF_MYSQL_DB,
        CONF_MYSQL_TIMEOUT,
        CONF_MYSQL_CHARSET,
        CONF_MYSQL_COLLATION,
        CONF_USE_TLS,
        *OPTION_KEYS,
    }
    assert {key for key, where in settings.items() if where == "Configure"} == set(
        OPTION_KEYS
    )


def test_the_settings_forms_hold_what_the_readme_says() -> None:
    """The reconfigure and options forms are the ones the table describes."""
    settings = _readme_settings()
    connection = {str(key) for key in get_connection_schema({}).schema}
    options = {str(key) for key in get_options_schema({}).schema}

    assert connection == {k for k, where in settings.items() if where == "Reconfigure"}
    assert options == {k for k, where in settings.items() if where == "Configure"}
