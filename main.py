#!/usr/bin/env python3
"""Disconnected Readiness Scorer — orchestrator.

Runs all (or selected) rules against a target repo and produces
an aggregate READY / WARNING / NOT READY score.
"""

import argparse
import importlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from rules.common import Finding, RuleResult

RULE_REGISTRY = {
    "csv": {
        "module": "rules.csv_relatedimages",
        "name": "image-manifest-complete",
        "needs_manifest": True,
    },
    "tags": {
        "module": "rules.no_image_tags",
        "name": "no-image-tags",
    },
    "egress": {
        "module": "rules.no_runtime_egress",
        "name": "no-runtime-egress",
    },
    "python": {
        "module": "rules.python_imports",
        "name": "python-imports-bundled",
    },
    "manifest": {
        "module": "rules.operator_manifest",
        "name": "operator-manifest",
        "is_manifest_rule": True,
    },
}

DEFAULT_RULES = ["csv", "tags", "egress", "python"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Score a repo's disconnected / air-gapped readiness.",
    )
    parser.add_argument(
        "repo_root", nargs="?", default=".",
        help="Path to the target repository (default: current directory)",
    )
    parser.add_argument(
        "--rules", default="all",
        help="Comma-separated rule aliases, or 'all' (default: all). "
             f"Available: {', '.join(RULE_REGISTRY)}",
    )
    parser.add_argument(
        "--report", choices=["markdown", "json"], default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--operator-path",
        help="Path to a pre-cloned opendatahub-operator. "
             "If omitted, clones to /tmp/opendatahub-operator when needed.",
    )
    return parser.parse_args(argv)


def resolve_rules(rules_arg):
    if rules_arg == "all":
        return list(DEFAULT_RULES)
    keys = [k.strip() for k in rules_arg.split(",")]
    for k in keys:
        if k not in RULE_REGISTRY:
            print(f"Unknown rule '{k}'. Available: {', '.join(RULE_REGISTRY)}", file=sys.stderr)
            sys.exit(1)
    return keys


def load_manifest(operator_path):
    mod = importlib.import_module("rules.operator_manifest")
    if not operator_path:
        operator_path = "/tmp/opendatahub-operator"
        target = Path(operator_path)
        if not (target / ".git").exists():
            print("  Cloning opendatahub-operator (shallow)...", file=sys.stderr)
            mod.clone_operator(target)
    manifest = mod.build_manifest(operator_path)
    env_vars = set(e.env_var for e in manifest.images)
    return manifest, env_vars


def adapt_manifest_result(manifest):
    result = RuleResult(rule="operator-manifest")
    all_vars = sorted(set(e.env_var for e in manifest.images))
    result.findings.append(Finding(
        severity="info",
        file="",
        line=0,
        image="",
        message=f"Parsed {len(all_vars)} RELATED_IMAGE vars "
                f"across {len(manifest.components)} components.",
    ))
    if manifest.known_issues:
        for issue in manifest.known_issues:
            result.findings.append(Finding(
                severity="warning",
                file="",
                line=0,
                image=issue,
                message=f"Known issue in operator manifest: {issue}",
            ))
    return result


def compute_score(results):
    if any(not r.passed for r in results):
        return "NOT READY"
    all_findings = [f for r in results for f in r.findings]
    if any(f.severity == "warning" for f in all_findings):
        return "WARNING"
    return "READY"


def print_summary(score, results):
    print(f"\nDisconnected Readiness Score: {score}\n")
    for r in results:
        blockers = sum(1 for f in r.findings if f.severity == "blocker")
        warnings = sum(1 for f in r.findings if f.severity == "warning")

        if blockers:
            tag = "BLOCKER"
        elif warnings:
            tag = "WARNING"
        else:
            tag = "PASS"

        summary_msg = ""
        if blockers:
            summary_msg = f"{blockers} blocker(s)"
        elif warnings:
            summary_msg = f"{warnings} warning(s)"
        else:
            summary_msg = "All checks passed"

        print(f"  {tag:<9} {r.rule:<25} {summary_msg}")

    total_blockers = sum(1 for r in results for f in r.findings if f.severity == "blocker")
    total_warnings = sum(1 for r in results for f in r.findings if f.severity == "warning")
    total_passed = sum(1 for r in results if r.passed)
    print(f"\nBlockers: {total_blockers} | Warnings: {total_warnings} | Passed: {total_passed}")


def render_json(score, results, repo_name):
    data = {
        "repo": repo_name,
        "date": date.today().isoformat(),
        "score": score,
        "rules": [
            {
                "name": r.rule,
                "passed": r.passed,
                "blockers": sum(1 for f in r.findings if f.severity == "blocker"),
                "warnings": sum(1 for f in r.findings if f.severity == "warning"),
                "findings": [
                    {"severity": f.severity, "file": f.file, "line": f.line,
                     "image": f.image, "message": f.message}
                    for f in r.findings
                ],
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2)


def _render_template_simple(template_str, context):
    """Minimal Jinja2-compatible renderer for the report template.

    Handles {{ var }}, {{ var | upper }}, and {% for x in y %}...{% endfor %}.
    """
    def resolve(expr, local_ctx):
        expr = expr.strip()
        filt = None
        if "|" in expr:
            expr, filt = expr.rsplit("|", 1)
            expr = expr.strip()
            filt = filt.strip()
        parts = expr.split(".")
        val = local_ctx
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p, "")
            else:
                val = getattr(val, p, "")
        val = str(val)
        if filt == "upper":
            val = val.upper()
        return val

    for_pattern = re.compile(
        r'\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}',
        re.DOTALL,
    )

    def expand_for(m):
        var_name = m.group(1)
        collection_name = m.group(2)
        body = m.group(3)
        collection = context.get(collection_name, [])
        pieces = []
        for item in collection:
            local = {**context, var_name: item}
            rendered = re.sub(
                r'\{\{\s*(.+?)\s*\}\}',
                lambda mv: resolve(mv.group(1), local),
                body,
            )
            pieces.append(rendered)
        return "".join(pieces)

    output = for_pattern.sub(expand_for, template_str)
    output = re.sub(
        r'\{\{\s*(.+?)\s*\}\}',
        lambda mv: resolve(mv.group(1), context),
        output,
    )
    return output


def render_markdown(score, results, repo_name):
    template_path = Path(__file__).parent / "templates" / "report.md"
    try:
        template_str = template_path.read_text()
    except OSError:
        return f"# Disconnected Readiness Report\n\n**Score:** {score}\n"

    context = {
        "repo_name": repo_name,
        "date": date.today().isoformat(),
        "score": score,
        "rules": [
            {
                "name": r.rule,
                "result": "PASS" if r.passed else "FAIL",
                "blockers": sum(1 for f in r.findings if f.severity == "blocker"),
                "warnings": sum(1 for f in r.findings if f.severity == "warning"),
            }
            for r in results
        ],
        "findings": [
            {
                "severity": f.severity,
                "rule": r.rule,
                "file": f.file,
                "line": f.line,
                "message": f.message,
            }
            for r in results
            for f in r.findings
            if f.severity in ("blocker", "warning")
        ],
    }

    try:
        import jinja2
        env = jinja2.Environment(autoescape=False)
        tmpl = env.from_string(template_str)
        return tmpl.render(**context)
    except ImportError:
        return _render_template_simple(template_str, context)


def main(argv=None):
    args = parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    repo_name = os.path.basename(repo_root)
    selected = resolve_rules(args.rules)

    manifest = None
    manifest_env_vars = None

    need_manifest = "manifest" in selected
    if "csv" in selected:
        csv_mod = importlib.import_module("rules.csv_relatedimages")
        pattern = csv_mod.detect_image_pattern(Path(repo_root))
        if pattern == "env_var":
            need_manifest = True

    if need_manifest:
        manifest, manifest_env_vars = load_manifest(args.operator_path)

    results = []
    for key in selected:
        entry = RULE_REGISTRY[key]
        mod = importlib.import_module(entry["module"])

        if entry.get("is_manifest_rule"):
            if manifest:
                results.append(adapt_manifest_result(manifest))
            else:
                manifest, manifest_env_vars = load_manifest(args.operator_path)
                results.append(adapt_manifest_result(manifest))
            continue

        if key == "csv" and manifest_env_vars is not None:
            result = mod.run(repo_root, manifest_env_vars=manifest_env_vars)
        else:
            result = mod.run(repo_root)
        results.append(result)

    score = compute_score(results)
    print_summary(score, results)

    if args.report == "json":
        print(render_json(score, results, repo_name))
    else:
        print(render_markdown(score, results, repo_name))

    return 0 if score != "NOT READY" else 1


if __name__ == "__main__":
    sys.exit(main())
