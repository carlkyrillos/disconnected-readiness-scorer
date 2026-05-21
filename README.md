[![codecov](https://codecov.io/gh/opendatahub-io/disconnected-readiness-scorer/graph/badge.svg?token=XE1XU6SQPB)](https://codecov.io/gh/opendatahub-io/disconnected-readiness-scorer)

# Disconnected Readiness Scorer

Score a repository's readiness for deployment in disconnected / air-gapped OpenShift environments.

## Why this exists

Disconnected and air-gapped deployments are a core requirement for many Red Hat OpenShift AI customers — particularly in government, financial services, and regulated industries where clusters have no outbound internet access. Analysis of ~96 open JIRA issues across RHAIRFE, RHAISTRAT, and RHOAIENG revealed that **75% of disconnected failures fall into four patterns detectable by static analysis before code is merged**:

| Pattern | % of Issues | Rule |
|---------|-------------|------|
| Missing images from manifests | ~30% | `csv-relatedimages` |
| Hardcoded external dependencies | ~25% | `python-imports` |
| Image tags instead of digests | ~10% | `no-image-tags` |
| Runtime external URL calls | ~10% | `no-runtime-egress` |

Today, none of these are checked automatically — failures are only discovered during manual disconnected testing, often weeks or months after the breaking change was merged. This scanner catches them at PR time.

## Quick start

### As a Claude Code skill

```bash
/disconnected-score
```

Run from the root of any RHOAI component repository. The skill definition is in [SKILL.md](SKILL.md).

### As a CLI tool

```bash
python3 main.py /path/to/target/repo                        # all default rules
python3 main.py /path/to/target/repo --rules csv,tags        # subset of rules
python3 main.py /path/to/target/repo --report json           # JSON output
python3 main.py /path/to/target/repo --operator-path /tmp/opendatahub-operator  # pre-cloned operator
```

Exit code is `0` for READY/WARNING, `1` for NOT READY.

### Individual rules

Each rule is a standalone script:

```bash
python3 rules/csv_relatedimages.py /path/to/target/repo
python3 rules/no_image_tags.py /path/to/target/repo
python3 rules/no_runtime_egress.py /path/to/target/repo
python3 rules/python_imports.py /path/to/target/repo
python3 rules/operator_manifest.py /path/to/opendatahub-operator
```

All rules output JSON to stdout with `rule`, `passed`, and `findings` fields.

## Output

```
Disconnected Readiness Score: WARNING

  BLOCKER  image-manifest-complete   2 images in code missing from CSV relatedImages
  PASS     no-image-tags             All checks passed
  WARNING  no-runtime-egress         1 warning(s)
  PASS     python-imports-bundled    All checks passed

Blockers: 1 | Warnings: 1 | Passed: 2
```

Reports are also generated as markdown (default) or JSON (`--report json`). Write to a file with `--output report.md`.

## Rules

### csv-relatedimages (alias: `csv`)

Auto-detects whether the target repo uses `RELATED_IMAGE_*` env vars (opendatahub-operator pattern) or static CSV `relatedImages`, then checks that every container image referenced in code is accounted for. When the env var pattern is detected, the orchestrator clones the opendatahub-operator and cross-references against the authoritative manifest.

Cross-reference produces three check types:
- Image ref uses a `RELATED_IMAGE` var not in the manifest &rarr; **blocker**
- Repo defines a var not in the manifest &rarr; **warning** (stale)
- Manifest vars not referenced in repo &rarr; **info**

### no-image-tags (alias: `tags`)

Enforces `@sha256:` digest refs; rejects mutable tags (`:latest`, `:v1.2.3`). Tags cannot be reliably mirrored. Production manifest directories escalate to **blocker** severity.

### no-runtime-egress (alias: `egress`)

Scans Go, Python, TypeScript, and shell source for patterns indicating outbound HTTP calls at runtime (`http.Get`, `requests.get`, `fetch()`, `curl`, etc.). Build-time usage in Dockerfiles, Makefiles, and CI scripts is excluded. Hardcoded external URLs are **blockers**; configurable/mirrorable endpoints are **info**.

### python-imports (alias: `python`)

Validates Python dependencies against the known-bundled list. Checks `requirements.txt`, `setup.py`, `pyproject.toml`, and runtime `pip install` calls. Unbundled runtime dependencies are **blockers**.

### operator-manifest (alias: `manifest`)

Parses the opendatahub-operator source to build the authoritative image manifest (100+ `RELATED_IMAGE_*` env vars across 18 components). Not run by default — included when `csv` detects the env var pattern or when explicitly selected with `--rules manifest`.

## Scoring

| Score | Meaning |
|-------|---------|
| **READY** | All rules pass |
| **WARNING** | No blockers, but warnings need manual review |
| **NOT READY** | One or more blocker-level failures |

Severity levels for individual findings:

| Severity | Meaning |
|----------|---------|
| `blocker` | Fails the score — must be fixed for disconnected readiness |
| `warning` | Needs manual review but doesn't fail the score |
| `info` | Excluded file or configurable pattern — informational only |

## Exclusions

All rules exclude these paths from blocker-level findings (they produce `info` severity instead):
- Test files: `*_test.go`, `test/`, `testdata/`, `e2e/`
- CI config: `.github/`, `.tekton/`
- Lint rules: `semgrep.yaml`

## Configuration

### `config/known_mirrors.yaml`

Approved internal registries and PyPI mirrors. Rules treat pulls from these as safe.

```yaml
registries:
  - registry.redhat.io
  - brew.registry.redhat.io
  - quay.io/opendatahub
  - quay.io/modh

pypi_mirrors:
  - https://pypi.corp.redhat.com/simple/
```

### `config/exceptions.yaml`

Per-repo rule exceptions for known false positives.

```yaml
exceptions:
  - repo: opendatahub-io/odh-dashboard
    rule: no-runtime-egress
    path: frontend/src/utilities/fetch.ts
    reason: "Uses cluster-internal API proxy, not external egress"
```

## Development

### Dependencies

```bash
pip install pytest pytest-cov pyyaml jinja2
```

`pyyaml` and `jinja2` are optional at runtime (rules degrade gracefully) but required for full test coverage.

### Running tests

```bash
python -m pytest tests/ -v                                 # all tests
python -m pytest tests/test_csv_relatedimages.py -v        # single file
python -m pytest tests/test_main.py::TestParseArgs -v      # single class
python -m pytest tests/ -v --cov=. --cov-report=term       # with coverage
```

CI runs on Python 3.9 and 3.12. Codecov enforces 80% patch coverage.

## License

Internal Red Hat / AI First Initiative.
