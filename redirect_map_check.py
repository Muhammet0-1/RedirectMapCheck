#!/usr/bin/env python3
"""Redirect Map Check 1.0.0 — bounded, offline exact-path CSV analysis."""

import argparse
import csv
import io
import json
import os
import re
import stat
import sys
from collections import defaultdict

VERSION = "1.0.0"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_LINE_BYTES = 2048
MAX_PATH_CHARS = 512
STATUSES = {"301", "302", "307", "308"}
PATH = re.compile(r"/(?:[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/?)?", re.ASCII)


class InputError(Exception):
    def __init__(self, code, line=None, field=None, exit_code=2):
        self.issue = {"code": code}
        if line is not None:
            self.issue["line"] = line
        if field is not None:
            self.issue["field"] = field
        self.exit_code = exit_code
        super().__init__(code)


def valid_path(value):
    return (
        len(value) <= MAX_PATH_CHARS
        and PATH.fullmatch(value) is not None
        and not any(part in {".", ".."} for part in value.split("/"))
    )


def read_rules(filename):
    """Read only the explicitly named regular file; never write it."""
    try:
        # Nonblocking open prevents a named pipe from waiting for a writer on POSIX.
        fd = os.open(filename, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise InputError("regular_file_required", exit_code=3)
            if info.st_size > MAX_BYTES:
                raise InputError("file_limit")
            data = source.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        raise InputError("file_unreadable", exit_code=3) from None
    if len(data) > MAX_BYTES:
        raise InputError("file_limit")
    try:
        content = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise InputError("invalid_utf8") from None
    if "\r" in content.replace("\r\n", ""):
        raise InputError("line_ending")
    for number, line in enumerate(content.split("\n"), 1):
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise InputError("line_limit", number)
    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header != ["from", "to", "status"] or reader.line_num != 1:
            raise InputError("header", 1)
        rules = []
        previous_line = 1
        for row in reader:
            line = previous_line + 1
            if reader.line_num != line:
                raise InputError("multiline_record", line)
            previous_line = reader.line_num
            if len(rules) >= MAX_ROWS:
                raise InputError("row_limit", line)
            if len(row) != 3:
                raise InputError("columns", line)
            for field, value in zip(("from", "to"), row[:2]):
                if not valid_path(value):
                    raise InputError("unsupported_path", line, field)
            if row[2] not in STATUSES:
                raise InputError("status", line, "status")
            rules.append({"from": row[0], "to": row[1],
                          "status": int(row[2]), "line": line})
        if not rules:
            raise InputError("no_rules", 2)
        return rules
    except csv.Error:
        raise InputError("malformed_csv", reader.line_num or 1) from None


def analyze(rules):
    grouped = defaultdict(lambda: defaultdict(list))
    for rule in rules:
        grouped[rule["from"]][(rule["to"], rule["status"])].append(rule["line"])
    duplicates, conflicts, self_loops, table = [], [], [], []
    edges = {}
    for source, variants in sorted(grouped.items()):
        choices = []
        for (target, status), lines in sorted(variants.items()):
            entry = {"from": source, "to": target, "status": status,
                     "lines": sorted(lines)}
            table.append(entry)
            choices.append({"to": target, "status": status, "lines": sorted(lines)})
            if len(lines) > 1:
                duplicates.append(entry.copy())
            if source == target:
                self_loops.append({**entry, "in_conflict": len(variants) > 1})
        if len(variants) > 1:
            conflicts.append({"from": source, "variants": choices})
        else:
            edges[source] = choices[0]

    memo, cycles, cycle_nodes = {}, [], set()
    # Functional graph, iterative walks and memoized suffixes: no recursion limit.
    for start in sorted(edges):
        trail, positions = [], {}
        current = start
        while current in edges and current not in memo and current not in positions:
            positions[current] = len(trail)
            trail.append(current)
            current = edges[current]["to"]
        if current in positions:
            members = trail[positions[current]:]
            smallest = min(range(len(members)), key=members.__getitem__)
            canonical = members[smallest:] + members[:smallest]
            cycle_id = "cycle:" + canonical[0]
            cycle_nodes.update(members)
            if len(members) > 1:
                cycles.append({"id": cycle_id, "paths": canonical + canonical[:1],
                               "length": len(members),
                               "lines": [edges[node]["lines"] for node in canonical]})
            for node in members:
                memo[node] = {"outcome": "cycle", "hops": len(members),
                              "final_path": None, "cycle_id": cycle_id,
                              "cycle_entry": node, "hops_to_cycle": 0,
                              "cycle_length": len(members)}
            trail = trail[:positions[current]]
        elif current not in memo:
            if current in grouped:  # Conflicted source has no chosen edge.
                memo[current] = {"outcome": "conflict", "hops": 0,
                                 "final_path": None, "blocked_at": current}
            else:
                memo[current] = {"outcome": "terminal", "hops": 0,
                                 "final_path": current}
        for node in reversed(trail):
            result = memo[edges[node]["to"]].copy()
            result["hops"] += 1
            if result["outcome"] == "cycle":
                result["hops_to_cycle"] += 1
            memo[node] = result

    routes = [{"from": start, "lines": edges[start]["lines"], **memo[start]}
              for start in sorted(edges)]
    chains = [route.copy() for route in routes
              if route["from"] not in cycle_nodes and route["hops"] >= 2]
    blocked = [route.copy() for route in routes if route["outcome"] == "conflict"]
    cycles.sort(key=lambda item: item["id"])
    counts = {"input_rows": len(rules), "unique_rules": len(table),
              "sources": len(grouped), "duplicates": len(duplicates),
              "conflicts": len(conflicts), "self_loops": len(self_loops),
              "cycles": len(cycles), "chains": len(chains),
              "blocked_routes": len(blocked)}
    found = any(counts[key] for key in
                ("duplicates", "conflicts", "self_loops", "cycles", "chains"))
    return {"schema_version": 1, "tool_version": VERSION,
            "result": "findings" if found else "clean", "analysis_performed": True,
            "reachability": "not_verified", "graph_scope": "unambiguous_rules_only",
            "counts": counts, "rules": table, "duplicates": duplicates,
            "conflicts": conflicts, "self_loops": self_loops,
            "cycles": cycles, "chains": chains, "blocked_routes": blocked,
            "routes": routes}


ERRORS = {
    "file_unreadable": ("Dosya okunamadı.", "Cannot read the file."),
    "regular_file_required": ("Düzenli dosya gerekli.", "A regular file is required."),
    "file_limit": ("Dosya 2 MiB sınırını aşıyor.", "File exceeds the 2 MiB limit."),
    "invalid_utf8": ("Geçersiz UTF-8.", "Invalid UTF-8."),
    "line_ending": ("Yalnız LF veya CRLF satır sonu desteklenir.", "Only LF or CRLF line endings are supported."),
    "line_limit": ("Fiziksel satır 2048 baytı aşıyor.", "Physical line exceeds 2048 bytes."),
    "header": ("Başlık tam olarak from,to,status olmalı.", "Header must be exactly from,to,status."),
    "multiline_record": ("Çok satırlı CSV kaydı desteklenmiyor.", "Multiline CSV records are unsupported."),
    "row_limit": ("2000 veri satırı sınırı aşıldı.", "More than 2000 data rows."),
    "columns": ("Her kayıtta üç sütun gerekli; boş satır kabul edilmez.", "Each record needs three columns; blank rows are rejected."),
    "unsupported_path": ("Desteklenmeyen veya çok uzun yol; README yol diline bakın.", "Unsupported or overlong path; see the README path grammar."),
    "status": ("Durum yalnız 301,302,307,308 olabilir.", "Status must be 301,302,307,308."),
    "no_rules": ("En az bir veri satırı gerekli.", "At least one data row is required."),
    "malformed_csv": ("Bozuk CSV.", "Malformed CSV."),
}


def text_report(report, lang):
    tr = lang == "tr"
    if not report["analysis_performed"]:
        lines = ["GİRDİ REDDEDİLDİ — analiz yapılmadı." if tr
                 else "INPUT REJECTED — no analysis performed."]
        for error in report["errors"]:
            location = ""
            if "line" in error:
                location += f" {'satır' if tr else 'line'} {error['line']}"
            if "field" in error:
                location += f" [{error['field']}]"
            lines.append(f"{error['code']}{location}: {ERRORS[error['code']][0 if tr else 1]}")
        return "\n".join(lines) + "\n"
    lines = [f"Redirect Map Check {VERSION}",
             ("Sonuç: bulgu var" if report["result"] == "findings" else "Sonuç: harita bulgusu yok")
             if tr else f"Result: {report['result']}",
             "Erişilebilirlik: doğrulanmadı. Ağ isteği yapılmadı." if tr
             else "Reachability: not verified. No network request was made.",
             "Çelişkili kaynaklar izlenmez. Sayılar grup/kaynak sayısıdır." if tr
             else "Conflicted sources are not followed. Counts refer to groups/sources."]
    labels = {
        "input_rows": "Girdi satırı", "unique_rules": "Tekil kural", "sources": "Kaynak",
        "duplicates": "Aynı satır tekrarları", "conflicts": "Çelişkiler",
        "self_loops": "Kendine yönlendirmeler", "cycles": "Çok düğümlü döngüler",
        "chains": "Zincirler", "blocked_routes": "Çelişkide duran yollar",
    }
    lines += [f"{labels[key] if tr else key}: {value}" for key, value in report["counts"].items()]
    for kind in ("duplicates", "conflicts", "self_loops", "cycles", "chains", "blocked_routes"):
        lines.append(f"\n{labels[kind] if tr else kind}:")
        if not report[kind]:
            lines.append("  yok" if tr else "  none")
        for item in report[kind]:
            if kind == "conflicts":
                lines.append(f"  {item['from']}:")
                for choice in item["variants"]:
                    lines.append(f"    -> {choice['to']} ({choice['status']}) {('satır' if tr else 'lines')} {choice['lines']}")
            elif kind == "cycles":
                lines.append(f"  {' -> '.join(item['paths'])}; {('satırlar' if tr else 'lines')} {item['lines']}")
            elif kind in {"chains", "blocked_routes"}:
                lines.append("  " + route_text(item, tr))
            else:
                lines.append(f"  {item['from']} -> {item['to']} ({item['status']}); {('satırlar' if tr else 'lines')} {item['lines']}")
    lines.append("\nTekil kurallar (kaynak satırları):" if tr else "\nUnique rules (source lines):")
    for rule in report["rules"]:
        lines.append(f"  {rule['from']} -> {rule['to']} ({rule['status']}); {rule['lines']}")
    lines.append("\nHer belirsiz olmayan kaynaktan sonuç:" if tr else "\nOutcome from each unambiguous source:")
    lines += ["  " + route_text(route, tr) for route in report["routes"]]
    return "\n".join(lines) + "\n"


def route_text(route, tr):
    prefix = f"{route['from']}; {('satırlar' if tr else 'lines')} {route['lines']}; {route['hops']} {('adım' if tr else 'hops')}"
    if route["outcome"] == "terminal":
        return prefix + f"; {('son yol' if tr else 'final path')}: {route['final_path']} ({('erişilebilirlik doğrulanmadı' if tr else 'reachability not verified')})"
    if route["outcome"] == "conflict":
        return prefix + f"; {('çelişkide durdu' if tr else 'blocked by conflict')}: {route['blocked_at']}; {('son yol yok' if tr else 'no final path')}"
    return prefix + f"; {('döngü girişi' if tr else 'cycle entry')}: {route['cycle_entry']}; {('girişe adım' if tr else 'hops to entry')}: {route['hops_to_cycle']}; {('döngü uzunluğu' if tr else 'cycle length')}: {route['cycle_length']}; {('son yol yok' if tr else 'no final path')}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline exact-path redirect CSV checker; see README for grammar and limits.")
    parser.add_argument("csv_file", help="Explicit local UTF-8 CSV file (from,to,status)")
    parser.add_argument("--lang", choices=("tr", "en"), default="tr", help="Text report language (default: tr)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    try:
        report = analyze(read_rules(args.csv_file))
        code = 1 if report["result"] == "findings" else 0
    except InputError as error:
        report = {"schema_version": 1, "tool_version": VERSION,
                  "result": "invalid_input" if error.exit_code == 2 else "io_error",
                  "analysis_performed": False, "errors": [error.issue]}
        code = error.exit_code
    if args.format == "json":
        # No timestamps, local filenames, locale-dependent text or random IDs.
        sys.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
    else:
        stream = sys.stderr if code in (2, 3) else sys.stdout
        stream.write(text_report(report, args.lang))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # A truncated report is never a successful result.
        sys.exit(3)
