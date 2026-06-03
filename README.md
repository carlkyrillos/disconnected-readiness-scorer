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
python3 main.py /path/to/target/repo --exceptions /path/to/exceptions.yaml      # custom exceptions
```

Exit code is `0` for READY/WARNING, `1` for NOT READY.

### Individual rules

Each rule is a standalone script:

```bash
python3 rules/csv_relatedimages.py /path/to/target/repo
python3 rules/params_env.py /path/to/target/repo
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

Auto-detects whether the target repo uses `RELATED_IMAGE_*` env vars (opendatahub-operator pattern) or static CSV `relatedImages`, then checks that every container image referenced in code is accounted for. When the env var pattern is detected, the orchestrator clones the opendatahub-operator and cross-references against the authoritative manifest. Only git-tracked files are scanned.

Cross-reference produces three check types:
- Image ref uses a `RELATED_IMAGE` var not in the manifest &rarr; **blocker**
- Repo defines a var not in the manifest &rarr; **warning** (stale)
- Manifest vars not referenced in repo &rarr; **info**

### params-env-wiring (alias: `params_env`)

Validates repos using the `params.env` + kustomize pattern. Requires `kustomize` binary on PATH. Validates the full wiring chain: `params.env` -> kustomize configMap -> rendered manifest -> Go `os.Getenv`. Detects hardcoded images not sourced from params.env (**blocker**), unwired params.env keys (**warning**), and orphan Go `os.Getenv` calls (**blocker**). Supports `.verify-params-env-ignore` for excluding keys. When the orchestrator provides operator manifest vars, cross-references mapped `RELATED_IMAGE_*` vars against the manifest.

### no-image-tags (alias: `tags`)

Enforces `@sha256:` digest refs; rejects mutable tags (`:latest`, `:v1.2.3`). Tags cannot be reliably mirrored. Source code files (`.go`, `.py`, `.ts`, `.sh`) escalate to **blocker** severity; manifest files produce **warnings**; test/build/CI files produce **info**. Directories managed by `params.env` + kustomize are skipped. HTTP/HTTPS URLs are excluded from image detection. Only git-tracked files are scanned.

### no-runtime-egress (alias: `egress`)

Scans Go, Python, TypeScript, and shell source for patterns indicating outbound HTTP calls at runtime (`http.Get`, `requests.get`, `fetch()`, `curl`, etc.). Build-time usage in Dockerfiles, Makefiles, and CI scripts is excluded. Test files produce **info** severity. Hardcoded external URLs are **blockers**; configurable/mirrorable endpoints are **info**. Only git-tracked files are scanned.

### python-imports (alias: `python`)

Validates Python dependencies against the known-bundled list. Checks `requirements.txt`, `setup.py`, `pyproject.toml`, and runtime `pip install` calls. Unbundled runtime dependencies are **blockers**. Only git-tracked files are scanned.

### operator-manifest (alias: `manifest`)

Parses the opendatahub-operator source to build the authoritative image manifest (100+ `RELATED_IMAGE_*` env vars across 18 components). Not run by default — included when `csv` or `params_env` detect a pattern needing cross-referencing, or when explicitly selected with `--rules manifest`.

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

- Test files: `*_test.go`, `test_*.py`, `test/`, `testdata/`, `e2e/`
- CI config: `.github/`, `.tekton/`
- Build files: `Dockerfile`, `Containerfile`, `*.Dockerfile`
- Lint rules: `semgrep.yaml`
- Untracked files: only git-tracked files are scanned

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

### `.verify-params-env-ignore`

Opt-out file for the `params_env` rule. Place it in the target repo root to exclude specific `params.env` keys from validation. Keys listed here skip probe checks and wiring validation — no blocker or warning will be raised for them.

```yaml
- key: odh_notebook_controller_image
  reason: "Managed externally by the operator, not needed in params.env wiring"

- key: odh_trustyai_service_image
  reason: "Component deprecated, will be removed in next release"
  reference: "https://issues.redhat.com/browse/RHOAIENG-12345"
```

Each entry requires `key` and `reason`. The optional `reference` field can link to a tracking issue.

### `config/exceptions.yaml`

Exception rules that downgrade matching blocker/warning findings to **info** severity. Use `--exceptions /path/to/file.yaml` to override the default location.

Each exception supports these fields:

| Field     | Required | Description                                                                  |
|-----------|----------|------------------------------------------------------------------------------|
| `rule`    | yes      | Rule name or comma-separated list (e.g. `no-image-tags, no-runtime-egress`)  |
| `reason`  | yes      | Why this exception exists                                                    |
| `path`    | no       | Glob pattern matched against finding file path (e.g. `install/*`)            |
| `image`   | no       | Glob pattern matched against finding image ref                               |
| `message` | no       | Substring match against finding message                                      |
| `repo`    | no       | Repository name filter (matches basename or `org/repo` form)                 |

```yaml
exceptions:
  - rule: no-image-tags, no-runtime-egress
    path: "install/*"
    reason: "Historical versioned release snapshots — immutable, not edited"

  - rule: no-runtime-egress
    repo: opendatahub-io/odh-dashboard
    reason: "Dashboard proxies all external calls through the backend"
```

## PR Integration

The primary use case for this tool is running it against Pull Requests in RHOAI component repositories, catching disconnected-breaking changes **before they merge** rather than weeks later during manual testing.

### GitHub Actions (recommended)

Add a workflow to each target repository that runs the scorer on every PR:

```yaml
# .github/workflows/disconnected-readiness.yml
name: Disconnected Readiness Check

on:
  pull_request:
    branches: [main]

jobs:
  disconnected-score:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Clone disconnected-readiness-scorer
        run: git clone --depth 1 https://github.com/opendatahub-io/disconnected-readiness-scorer.git /tmp/scorer

      - name: Install kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Install dependencies
        run: pip install pyyaml

      - name: Run disconnected readiness check
        run: python3 /tmp/scorer/main.py . --report json --output disconnected-report.json

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: disconnected-readiness-report
          path: disconnected-report.json
```

The workflow exits with code `1` when blocker-level findings are present, which will fail the PR check.

### Targeted rules per repository

Not every rule applies to every repo. Use `--rules` to run only the relevant checks:

| Repository type                             | Recommended rules              |
|---------------------------------------------|--------------------------------|
| Operators using `RELATED_IMAGE_*` env vars  | `csv,tags,manifest`            |
| Components using `params.env` + kustomize   | `params_env,tags,egress`       |
| Python ML components (e.g., model serving)  | `python,tags,egress`           |
| Go services / controllers                   | `csv,tags,egress`              |
| Frontend / dashboard                        | `egress`                       |

Example for a Python-heavy repo:

```yaml
      - name: Run disconnected readiness check
        run: python3 /tmp/scorer/main.py . --rules python,tags,egress
```

### PR comment reporting

To post results as a PR comment instead of just failing the check, pipe the markdown report into the GitHub CLI:

```yaml
      - name: Run disconnected readiness check
        id: score
        run: |
          python3 /tmp/scorer/main.py . --report markdown --output disconnected-report.md || true

      - name: Post PR comment
        if: github.event_name == 'pull_request'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          {
            echo "## Disconnected Readiness Report"
            echo ""
            cat disconnected-report.md
          } | gh pr comment ${{ github.event.pull_request.number }} --body-file -
```

### Running locally on a PR branch

To check a PR branch before pushing:

```bash
# From the component repo, on your PR branch
python3 /path/to/disconnected-readiness-scorer/main.py .
```

Or using the Claude Code skill from the component repo root:

```bash
/disconnected-score
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
