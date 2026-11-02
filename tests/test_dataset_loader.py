import gzip

from src.data import DatasetValidationError, load_edge_list
from src.data.loader import sha256_file
from src.data.validation import validate_same_graph
from tests.helpers import TemporaryFilesTest


class LoaderTests(TemporaryFilesTest):
    def test_plain_and_gzip_preserve_sparse_ids_headers_and_self_loops(self):
        text = "# header\n\n3 19\n19\t93 # inline comment\n93 93\n"
        plain = self.write(text)
        compressed = self.root / "edges.txt.gz"
        with gzip.open(compressed, "wt", encoding="utf-8") as stream:
            stream.write(text)
        original_hash = sha256_file(compressed)
        for directed in (True, False):
            with self.subTest(directed=directed):
                first = load_edge_list(plain, directed=directed)
                second = load_edge_list(compressed, directed=directed)
                validate_same_graph(first.graph, second.graph)
                self.assertEqual(set(second.graph), {3, 19, 93})
                self.assertEqual(second.graph.is_directed(), directed)
                self.assertEqual(second.statistics.edge_records, 3)
                self.assertEqual(second.statistics.comment_lines, 1)
                self.assertEqual(second.statistics.blank_lines, 1)
                self.assertEqual(second.source_sha256, original_hash)
        self.assertEqual(sha256_file(compressed), original_hash)

    def test_directed_reverse_edges_are_distinct(self):
        loaded = load_edge_list(self.write("7 90\n90 7\n"), directed=True)
        self.assertEqual(set(loaded.graph.edges), {(7, 90), (90, 7)})

    def test_undirected_reverse_edges_are_duplicates(self):
        with self.assertRaisesRegex(DatasetValidationError, r":2: 1 duplicate"):
            load_edge_list(self.write("7 90\n90 7\n"), directed=False)

    def test_exact_duplicates_and_repeated_loops_are_rejected(self):
        for text in ("1 2\n1 2\n", "8 8\n8 8\n"):
            for directed in (True, False):
                with self.subTest(text=text, directed=directed):
                    with self.assertRaisesRegex(DatasetValidationError, "duplicate"):
                        load_edge_list(self.write(text), directed=directed)

    def test_malformed_lines_include_source_line_number(self):
        for line in ("1", "1 2 3", "x 2", "1 2.5"):
            with self.subTest(line=line):
                with self.assertRaisesRegex(DatasetValidationError, r"edges.txt:2:"):
                    load_edge_list(self.write("# header\n" + line), directed=True)

    def test_empty_or_comment_only_input_is_rejected(self):
        for text in ("", "# comment\n\n"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(DatasetValidationError, "no edges"):
                    load_edge_list(self.write(text), directed=True)

    def test_missing_file_is_reported(self):
        with self.assertRaisesRegex(DatasetValidationError, "Cannot read edge list"):
            load_edge_list(self.root / "absent.gz", directed=False)

    def test_invalid_and_truncated_gzip_are_rejected(self):
        complete = gzip.compress(b"1 2\n3 4\n")
        for contents in (b"not gzip", complete[:-5]):
            with self.subTest(contents=contents):
                path = self.root / "broken.gz"
                path.write_bytes(contents)
                with self.assertRaisesRegex(DatasetValidationError, "Cannot read edge list"):
                    load_edge_list(path, directed=True)

    def test_archive_is_not_treated_as_edge_list(self):
        with self.assertRaisesRegex(DatasetValidationError, "Archive"):
            load_edge_list(self.root / "facebook.tar.gz", directed=False)
