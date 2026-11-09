# Redirect Map Check

Version 1.0.0. A small Python CLI that checks an exact-path CSV redirect plan for duplicate rows, conflicting rules, self-redirects, multi-node cycles and chains. [Türkçe](README.tr.md).

Only the explicitly supplied file is read. No network, HTTP requests, crawling, telemetry, automatic fixes or server configuration generation. The source CSV and server settings are not modified. A final path means that no further rule exists in this map. Its existence, response status and reachability remain **not verified**. A clean map does not establish working redirects, SEO outcomes or security.

## Run

From the extracted `redirect-map-check` folder, use your existing Python interpreter. No installation or third-party runtime package is needed. The intended syntax baseline is Python 3.10+. The actual tested platform is CachyOS Linux x86_64, CPython 3.14.9, run from a terminal on KDE. Windows, macOS and other Python versions were not tested; compatibility there is unverified.

```text
python -B redirect_map_check.py examples/clean.csv --lang en
python -B redirect_map_check.py examples/chain.csv --lang tr
python -B redirect_map_check.py examples/mixed.csv --format json
python -B -m unittest discover -s tests -v
```

The first example exits 0; the chain and mixed examples exit 1; `examples/invalid.csv` exits 2. Exit 1 is expected for examples with findings. Supply an explicit local filename, quoted if it contains spaces. There is no stdin, URL, directory or automatic wildcard discovery mode. `--help` displays the English CLI synopsis; `--version` prints the version.

## Input grammar and limits

UTF-8, optionally one initial BOM; comma-separated fields, LF or CRLF endings. The first physical line must contain exactly `from,to,status`, in that order. Standard double-quoted CSV fields are accepted. Each data record occupies exactly one physical line with three nonempty fields. Blank records, comments, multiline fields and missing/extra columns are rejected. Whitespace is never trimmed.

```csv
from,to,status
/old-guide,/guides,301
/guides,/learn,308
```

A path is `/`, or a single leading slash followed by nonempty slash-separated segments and an optional single trailing slash. Segment characters are only ASCII `A-Z a-z 0-9 _ - .`; a segment cannot be `.` or `..`. `/guide`, `/Guide/`, `/docs/page.html` and `/.well-known/file` are accepted. Case and trailing slashes remain distinct. No URL decoding, canonicalization or merging takes place.

Full URLs, `//host/path`, relative paths, query strings, fragments, every percent-encoded path, Unicode, whitespace, backslashes, repeated interior slashes, wildcards and regex syntax are rejected. `/a%2Fb` and `/a?x=1` are not interpreted as supported paths. The same-site premise is a requirement on the map you supply; the tool cannot verify a host identity. Status must be exactly `301`, `302`, `307` or `308`. Suitability, request-method semantics and live HTTP behavior cannot be established from the CSV.

Limits: 2 MiB (2,097,152 bytes including BOM), 2,000 data records excluding the header, 512 ASCII characters per path, 2,048 UTF-8 bytes per physical line before LF (including CR in CRLF, excluding the decoded initial BOM). Input must be a regular file; a POSIX FIFO is rejected without waiting. Symlinks to regular files can be read. File size is checked before and after a bounded read. Oversize input is not analyzed. These are independent ceilings, not a claim that all can be reached simultaneously by valid input.

## Finding semantics

- **Duplicates:** identical source, target and status; all physical line numbers are preserved. The graph uses one edge.
- **Conflicts:** one source has differing targets or statuses. Every variant is shown, none is chosen. Routes reaching it stop in `blocked_routes`.
- **Self-redirects:** source equals target, also reported when a conflicted variant contains one (`in_conflict=true`).
- **Cycles:** closed paths of at least two nodes in the unambiguous graph. Reported once, rotated to the smallest ASCII path. Self-redirects are separate.
- **Chains:** at least two known redirect edges from a source outside a cycle. Each starting source is a separate finding: `/a -> /b -> /c -> /d` gives three hops from `/a` and two from `/b`. A chain can end at a terminal, enter a cycle, or stop at a conflict. For cycles, `hops` counts edges until the first repeated path, including one cycle lap; `hops_to_cycle` counts only edges before entry. At a conflict only known edges count. Cycles and conflicts have no final path.

No absence-of-cycles claim is made about rules hidden behind conflicts. `graph_scope=unambiguous_rules_only` records this boundary. Server precedence, rules outside the map, host/HTTPS handling and slash normalization remain unknown. Reports contain the supplied paths; review locally before sharing. Included examples are synthetic.

## Reports and exits

Text is the default format; `--lang tr|en` selects its language (default TR). Valid-input text goes to stdout; input/file error text goes to stderr. `--format json` writes one JSON object to stdout, including input/file errors. The CLI has no output-file option; shell redirection is your choice.

JSON uses stable English keys; `--lang` does not change its bytes. Identical input and tool version produce identical JSON: sorted keys, stable record order, LF termination, no timestamp, local filename or random ID. `schema_version=1`, `tool_version=1.0.0`. `result` is `clean` or `findings` for valid input, `invalid_input` or `io_error` otherwise.

`rules` lists every unique rule and its physical `lines`. `routes` gives an `outcome=terminal|cycle|conflict` for each unambiguous source. Separate lists are `duplicates`, `conflicts`, `self_loops`, `cycles`, `chains`, `blocked_routes`. `counts` counts groups/starting sources: duplicate count is not excess-row count; chain count is not component count. Global `reachability=not_verified` applies to every final path. Full paths are not repeated for every source; follow the shared rule table if needed.

Any invalid or unsupported record stops the entire analysis. The first error code includes a physical line and field where available. `analysis_performed=false`; no partial counts, routes or clean result are emitted. Decode, file-size and read errors may not have a reliable line number.

| Exit | Meaning |
| --- | --- |
| 0 | Valid map with no in-scope findings; also help/version. No live success claim. |
| 1 | At least one duplicate, conflict, self-redirect, cycle or chain. |
| 2 | Invalid, unsupported or oversized input, or CLI usage error. No analysis result. |
| 3 | File read/type error or caught broken output pipe. |

Argparse usage errors go to stderr as usage text, even if JSON was requested; they are not JSON. Unexpected operating-system termination may produce other process codes.

## Validation and scope

Canonical check: `python -B -m unittest discover -s tests -v`. The 45 tests cover synthetic cases and compare 100 deterministic small random graphs with an independent simple walker. Python socket audit events fail in the test process and CLI children; no real target is used. A test verifies the guard itself by rejecting local socket creation. Input SHA-256 and mtime remain unchanged. The source and extracted distribution were independently tested with the same suite. See [QA](QA.md) for the tested platform and scope. This is local validation, not a GitHub CI result.

MIT License. Copyright (c) 2026 Muhammet Sarıdoğan. See [LICENSE](LICENSE). Repository: [Muhammet0-1/RedirectMapCheck](https://github.com/Muhammet0-1/RedirectMapCheck).
