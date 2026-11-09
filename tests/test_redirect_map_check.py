"""Synthetic behavioral tests. Any Python socket audit event fails immediately."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("redirect_map_check", ROOT / "redirect_map_check.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def no_network(event, args):
    if event.startswith("socket."):
        raise AssertionError("Network use forbidden in synthetic tests: " + event)


sys.addaudithook(no_network)
CHILD = """import sys,runpy
def guard(event,args):
    if event.startswith('socket.'):
        raise AssertionError('Network use forbidden: '+event)
sys.addaudithook(guard)
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
"""


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "map.csv"

    def read(self, content):
        self.path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return tool.read_rules(self.path)

    def report(self, rows):
        return tool.analyze(self.read("from,to,status\n" + rows))

    def reject(self, content, code, line=None):
        with self.assertRaises(tool.InputError) as caught:
            self.read(content)
        self.assertEqual(caught.exception.issue["code"], code)
        if line is not None:
            self.assertEqual(caught.exception.issue["line"], line)
        self.assertEqual(caught.exception.exit_code, 2)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-c", CHILD,
                               str(ROOT / "redirect_map_check.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_clean_single_redirect_and_unverified_terminal(self):
        report = self.report("/old,/new,301\n")
        self.assertEqual(report["result"], "clean")
        self.assertEqual(report["reachability"], "not_verified")
        self.assertEqual(report["routes"], [{"from": "/old", "lines": [2],
                                          "outcome": "terminal", "hops": 1, "final_path": "/new"}])

    def test_all_four_statuses(self):
        report = self.report("".join(f"/s{n},/t{n},{n}\n" for n in (301, 302, 307, 308)))
        self.assertEqual(report["result"], "clean")

    def test_identical_duplicates_preserve_all_lines(self):
        report = self.report("/a,/b,301\n" * 3)
        self.assertEqual(report["counts"]["duplicates"], 1)
        self.assertEqual(report["duplicates"][0]["lines"], [2, 3, 4])
        self.assertEqual(report["routes"][0]["hops"], 1)
        self.assertEqual(report["result"], "findings")

    def test_conflicting_targets_never_choose_edge(self):
        report = self.report("/a,/b,301\n/a,/c,301\n/x,/a,301\n")
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual([r["from"] for r in report["routes"]], ["/x"])
        self.assertEqual(report["blocked_routes"][0]["blocked_at"], "/a")
        self.assertIsNone(report["blocked_routes"][0]["final_path"])

    def test_conflicting_status_even_with_same_target(self):
        report = self.report("/a,/b,301\n/a,/b,302\n")
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["routes"], [])

    def test_duplicate_and_conflict_are_separate(self):
        report = self.report("/a,/b,301\n/a,/b,301\n/a,/c,308\n")
        self.assertEqual((len(report["duplicates"]), len(report["conflicts"])), (1, 1))

    def test_self_loop_separate_from_multi_node_cycles(self):
        report = self.report("/a,/a,301\n")
        self.assertEqual(len(report["self_loops"]), 1)
        self.assertEqual(report["cycles"], [])
        self.assertEqual(report["chains"], [])
        self.assertEqual(report["routes"][0]["cycle_length"], 1)

    def test_self_loop_variant_in_conflict(self):
        report = self.report("/a,/a,301\n/a,/b,301\n")
        self.assertTrue(report["self_loops"][0]["in_conflict"])
        self.assertEqual(report["routes"], [])

    def test_two_node_cycle_and_lines(self):
        report = self.report("/b,/a,301\n/a,/b,302\n")
        self.assertEqual(report["cycles"], [{"id": "cycle:/a", "paths": ["/a", "/b", "/a"],
                                            "length": 2, "lines": [[3], [2]]}])
        self.assertEqual(report["chains"], [])

    def test_multi_node_cycle(self):
        report = self.report("/c,/a,301\n/a,/b,302\n/b,/c,307\n")
        self.assertEqual(report["cycles"][0]["paths"], ["/a", "/b", "/c", "/a"])

    def test_chain_entering_cycle_has_no_final(self):
        report = self.report("/x,/y,301\n/y,/a,301\n/a,/b,301\n/b,/a,301\n")
        x = next(r for r in report["chains"] if r["from"] == "/x")
        self.assertEqual((x["hops"], x["hops_to_cycle"], x["cycle_length"]), (4, 2, 2))
        self.assertIsNone(x["final_path"])

    def test_chain_entering_self_loop(self):
        report = self.report("/x,/a,301\n/a,/a,301\n")
        self.assertEqual(report["chains"][0]["hops"], 2)
        self.assertEqual(report["chains"][0]["outcome"], "cycle")

    def test_chain_terminal_and_suffix_lengths(self):
        report = self.report("/a,/b,301\n/b,/c,302\n/c,/d,307\n")
        self.assertEqual([(r["from"], r["hops"], r["final_path"]) for r in report["chains"]],
                         [("/a", 3, "/d"), ("/b", 2, "/d")])

    def test_chain_blocked_by_conflict(self):
        report = self.report("/a,/b,301\n/b,/c,301\n/c,/d,301\n/c,/e,301\n")
        self.assertEqual(report["chains"][0]["hops"], 2)
        self.assertEqual(report["chains"][0]["blocked_at"], "/c")

    def test_independent_components(self):
        report = self.report("/a,/b,301\n/b,/a,301\n/z,/done,308\n/k,/k,302\n/p,/q,307\n/q,/r,301\n")
        self.assertEqual((report["counts"]["cycles"], report["counts"]["self_loops"],
                          report["counts"]["chains"]), (1, 1, 1))

    def test_case_and_trailing_slash_remain_distinct(self):
        report = self.report("/A,/a,301\n/a/,/A/,302\n")
        self.assertEqual(report["result"], "clean")
        self.assertEqual([r["final_path"] for r in report["routes"]], ["/a", "/A/"])

    def test_root_and_dotted_file(self):
        report = self.report("/,/index.html,301\n/.well-known/file_1-2,/ok,308\n")
        self.assertEqual(report["result"], "clean")

    def test_bom_crlf_quoted_fields(self):
        rules = self.read('\ufeff"from","to","status"\r\n"/a","/b","301"\r\n')
        self.assertEqual(rules[0]["line"], 2)

    def test_no_final_newline(self):
        self.assertEqual(len(self.read("from,to,status\n/a,/b,301")), 1)

    def test_empty_header_only_and_blank_record(self):
        for content, code in [("", "header"), ("from,to,status\n", "no_rules"),
                              ("from,to,status\n\n", "columns")]:
            with self.subTest(content=content):
                self.reject(content, code)

    def test_header_schema_exact(self):
        for header in ["to,from,status", "from,to", "from,to,status,extra", "from,from,status",
                       " from,to,status", "FROM,to,status"]:
            with self.subTest(header=header):
                self.reject(header + "\n/a,/b,301\n", "header", 1)

    def test_missing_extra_columns_and_blank_fields(self):
        for row, code in [("/a,/b", "columns"), ("/a,/b,301,x", "columns"),
                          (",/b,301", "unsupported_path"), ("/a,,301", "unsupported_path"),
                          ("/a,/b,", "status")]:
            with self.subTest(row=row):
                self.reject("from,to,status\n" + row + "\n", code, 2)

    def test_malformed_quotes(self):
        for row in ['"/a,/b,301', '"/a"oops,/b,301']:
            with self.subTest(row=row):
                self.reject("from,to,status\n" + row, "malformed_csv", 2)

    def test_multiline_record(self):
        self.reject('from,to,status\n"/a\nb",/c,301\n', "multiline_record", 2)

    def test_bad_utf8(self):
        self.reject(b"from,to,status\n/a,/b,301\n\xff", "invalid_utf8")

    def test_lone_cr_rejected(self):
        self.reject("from,to,status\r/a,/b,301\r", "line_ending")

    def test_unsupported_paths_in_both_columns(self):
        paths = ["https://example.test/a", "//example.test/a", "a", "/a?x=1", "/a#x",
                 "/a*", "/(a)", "/a+", "/a%2Fb", "/a%20b", "/a%252Fb", "/a\\b",
                 "/a//b", "/./b", "/a/..", "/ç", "/a b", " /a", "/a ", "/a\t", "/a\x00"]
        for path in paths:
            for field in (0, 1):
                row = ["/a", "/b", "301"]
                row[field] = path
                with self.subTest(path=path, field=field):
                    self.reject("from,to,status\n" + ",".join(row) + "\n", "unsupported_path", 2)

    def test_invalid_status(self):
        for status in ("200", "303", "300", "0301", "301.0", " 301", "301 ", "-301"):
            with self.subTest(status=status):
                self.reject(f"from,to,status\n/a,/b,{status}\n", "status", 2)

    def test_path_length_boundary(self):
        path = "/" + "a" * (tool.MAX_PATH_CHARS - 1)
        self.assertEqual(self.report(f"{path},/b,301\n")["result"], "clean")
        self.reject(f"from,to,status\n{path}a,/b,301\n", "unsupported_path", 2)

    def test_row_limit_and_long_chain_without_recursion(self):
        rows = "".join(f"/p{n},/p{n+1},301\n" for n in range(tool.MAX_ROWS))
        report = self.report(rows)
        self.assertEqual(len(report["chains"]), tool.MAX_ROWS - 1)
        self.assertEqual(report["routes"][0]["hops"], tool.MAX_ROWS)
        self.assertEqual(report["routes"][0]["final_path"], f"/p{tool.MAX_ROWS}")
        self.reject("from,to,status\n" + rows + "/extra,/done,301\n", "row_limit", tool.MAX_ROWS + 2)

    def test_file_byte_boundary(self):
        content = "from,to,status\n/a,/b,301\n"
        with patch.object(tool, "MAX_BYTES", len(content.encode())):
            self.assertEqual(len(self.read(content)), 1)
            self.reject(content + "\n", "file_limit")
        self.reject(b"a" * (tool.MAX_BYTES + 1), "file_limit")

    def test_exact_real_file_byte_limit_not_misreported(self):
        # Byte cap independently accepts the boundary; invalid content then fails grammar.
        self.path.write_bytes(b"a" * tool.MAX_BYTES)
        with self.assertRaises(tool.InputError) as caught:
            tool.read_rules(self.path)
        self.assertEqual(caught.exception.issue["code"], "line_limit")

    def test_physical_line_boundary(self):
        self.reject("from,to,status\n" + "a" * tool.MAX_LINE_BYTES + "\n", "columns", 2)
        self.reject("from,to,status\n" + "a" * (tool.MAX_LINE_BYTES + 1) + "\n", "line_limit", 2)

    def test_growth_after_stat_is_bounded(self):
        self.path.write_bytes(b"a" * (tool.MAX_BYTES + 1))
        fake = type("Info", (), {"st_size": 0, "st_mode": 0o100644})()
        with patch.object(tool.os, "fstat", return_value=fake):
            with self.assertRaises(tool.InputError) as caught:
                tool.read_rules(self.path)
        self.assertEqual(caught.exception.issue["code"], "file_limit")

    def test_directory_and_missing_file_are_io_error(self):
        for path in (Path(self.temp.name), self.path):
            with self.subTest(path=path):
                with self.assertRaises(tool.InputError) as caught:
                    tool.read_rules(path)
                self.assertEqual(caught.exception.exit_code, 3)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_fifo_rejected_without_waiting(self):
        os.mkfifo(self.path)
        process = self.cli(self.path, "--format", "json")
        self.assertEqual(process.returncode, 3)
        self.assertFalse(json.loads(process.stdout)["analysis_performed"])

    def test_source_bytes_and_metadata_unchanged(self):
        self.read("from,to,status\n/a,/b,301\n/b,/c,301\n")
        before = (hashlib.sha256(self.path.read_bytes()).hexdigest(), self.path.stat().st_mtime_ns)
        self.cli(self.path, "--format", "json")
        after = (hashlib.sha256(self.path.read_bytes()).hexdigest(), self.path.stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["map.csv"])

    def test_deterministic_json_across_runs_languages_and_filename(self):
        self.read("from,to,status\n/b,/c,301\n/a,/b,302\n/a,/d,307\n/x,/x,308\n")
        first = self.cli(self.path, "--format", "json", "--lang", "tr")
        copy = self.path.with_name("other.csv")
        copy.write_bytes(self.path.read_bytes())
        second = self.cli(copy, "--format", "json", "--lang", "en")
        self.assertEqual(first.returncode, 1)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        self.assertNotIn(str(self.path), first.stdout)

    def test_cli_codes_zero_one_two_three(self):
        self.read("from,to,status\n/a,/b,301\n")
        self.assertEqual(self.cli(self.path).returncode, 0)
        self.read("from,to,status\n/a,/a,301\n")
        self.assertEqual(self.cli(self.path).returncode, 1)
        self.path.write_text("wrong\n", encoding="utf-8")
        self.assertEqual(self.cli(self.path).returncode, 2)
        self.assertEqual(self.cli(self.path.with_name("absent.csv")).returncode, 3)

    def test_invalid_tail_never_produces_partial_clean(self):
        self.path.write_text("from,to,status\n/a,/b,301\n/c,https://example.test,301\n", encoding="utf-8")
        result = self.cli(self.path, "--format", "json")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report["analysis_performed"])
        self.assertNotIn("counts", report)
        self.assertNotIn("routes", report)
        self.assertEqual(report["errors"][0]["line"], 3)

    def test_missing_cli_argument_not_success(self):
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_tr_en_text_and_error_streams(self):
        self.read("from,to,status\n/a,/b,301\n/b,/c,301\n")
        tr = self.cli(self.path, "--lang", "tr")
        en = self.cli(self.path, "--lang", "en")
        self.assertIn("son yol: /c", tr.stdout)
        self.assertIn("erişilebilirlik doğrulanmadı", tr.stdout)
        self.assertIn("final path: /c", en.stdout)
        self.assertIn("reachability not verified", en.stdout)
        self.path.write_text("from,to,status\n/a,/b,200\n", encoding="utf-8")
        error = self.cli(self.path, "--lang", "en")
        self.assertEqual(error.stdout, "")
        self.assertIn("line 2 [status]", error.stderr)

    def test_cli_help_version_and_invalid_option(self):
        self.assertEqual(self.cli("--help").returncode, 0)
        self.assertEqual(self.cli("--version").stdout.strip(), tool.VERSION)
        self.assertEqual(self.cli(self.path, "--format", "yaml").returncode, 2)

    def test_network_guard_is_active(self):
        import socket
        with self.assertRaisesRegex(AssertionError, "Network use forbidden"):
            socket.socket()

    def test_small_graphs_match_independent_naive_oracle(self):
        rng = random.Random(947)
        for attempt in range(100):
            nodes = [f"/n{n}" for n in range(9)]
            edges = {node: rng.choice(nodes + ["/end"]) for node in nodes if rng.random() < .8}
            if not edges:
                continue
            report = self.report("".join(f"{a},{b},301\n" for a, b in edges.items()))
            for actual in report["routes"]:
                seen, current, hops = {}, actual["from"], 0
                while current in edges and current not in seen:
                    seen[current] = hops
                    current = edges[current]
                    hops += 1
                with self.subTest(attempt=attempt, source=actual["from"]):
                    self.assertEqual(actual["hops"], hops)
                    if current in seen:
                        self.assertEqual(actual["outcome"], "cycle")
                        self.assertEqual(actual["cycle_entry"], current)
                        self.assertEqual(actual["hops_to_cycle"], seen[current])
                        self.assertEqual(actual["cycle_length"], hops - seen[current])
                    else:
                        self.assertEqual(actual["outcome"], "terminal")
                        self.assertEqual(actual["final_path"], current)


if __name__ == "__main__":
    unittest.main()
