# Validation / doğrulama

Version 1.0.0 uses only the Python standard library. The actual tested platform is CachyOS Linux x86_64, CPython 3.14.9. Python 3.10+ is the intended syntax baseline; other interpreter versions, Windows and macOS were not tested.

Canonical command, from the repository or extracted distribution directory:

```text
python -B -m unittest discover -s tests -v
```

The source and extracted ZIP independently passed 45 tests. The suite covers clean rules, all four statuses, duplicate rows, conflicting targets/statuses, self-loops, multi-node cycles, chains entering cycles, independent components, terminal/conflict outcomes, chain lengths, case and trailing-slash distinctions, CSV quoting/BOM/CRLF, invalid or unsupported input, UTF-8, file/row/path limits, a 2,000-hop chain, deterministic JSON, exit codes, TR/EN output and source preservation. It also checks 100 deterministic small graphs against an independent simple walker; those are cases within the suite, not 100 additional unittest methods.

Python socket audit events are forbidden in the test process and CLI subprocesses. A guard test rejects socket creation before network use. No real site, private URL, credential or customer data is used. Source CSV SHA-256 and mtime remain unchanged. These tests do not verify live HTTP responses or reachability.

The main Python source SHA-256 is `9709521f2d478929df85dcb9fdd604d265c64a8690d162f8d4a3f51436260fe9`.

No GitHub Actions workflow is included. Passing local tests must not be reported as GitHub CI. This file records the tested release scope; it contains no private session or review logs.

Kaynak ve ZIP kopyası ayrı 45/45 test geçti. Windows/macOS ve canlı HTTP doğrulaması yapılmadı. Testler gerçek sitenin çalıştığını, SEO sonucunu veya güvenliği kanıtlamaz. MIT lisansı LICENSE dosyasındadır.
