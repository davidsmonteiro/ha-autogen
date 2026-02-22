"""YAML syntax validation using ruamel.yaml."""

from __future__ import annotations

from io import StringIO

from ruamel.yaml import YAML, YAMLError

from autogen.validator.models import ValidationIssue, ValidationResult, ValidationSeverity


def check_yaml_syntax(yaml_str: str) -> ValidationResult:
    """Parse YAML and check for syntax errors.

    Returns a ValidationResult with valid=True and the parsed dict on success,
    or valid=False with an error-level issue on failure.
    """
    if not yaml_str or not yaml_str.strip():
        return ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.error,
                    check_name="yaml_syntax",
                    message="Empty YAML output",
                )
            ],
        )

    yaml = YAML()
    yaml.preserve_quotes = True

    try:
        parsed = yaml.load(StringIO(yaml_str))
    except YAMLError as e:
        line = None
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            line = e.problem_mark.line + 1  # 0-indexed to 1-indexed

        return ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.error,
                    check_name="yaml_syntax",
                    message=str(e),
                    line=line,
                )
            ],
        )

    if parsed is None:
        return ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.error,
                    check_name="yaml_syntax",
                    message="YAML parsed to empty/null value",
                )
            ],
        )

    # Convert ruamel types to plain dict for downstream use
    parsed_dict = dict(parsed) if hasattr(parsed, "items") else parsed

    return ValidationResult(valid=True, yaml_parsed=parsed_dict)
