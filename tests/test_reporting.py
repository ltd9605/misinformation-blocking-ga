"""Check report navigation after moving documents out of the repository root."""

from pathlib import Path
import tempfile
import unittest

from experiments.reporting import DOCUMENT_PATHS, project_document, write_project_report
from src.data.specs import PROJECT_ROOT


class ProjectReportingTests(unittest.TestCase):
    def test_all_relocated_documents_exist(self) -> None:
        for legacy, current in DOCUMENT_PATHS.items():
            with self.subTest(document=legacy):
                self.assertEqual(project_document(legacy), PROJECT_ROOT / current)
                self.assertTrue(project_document(legacy).is_file())

    def test_unmoved_paths_and_absolute_paths_keep_their_locations(self) -> None:
        for relative in ("README.md", "docs/main_experiments_results/results.csv"):
            with self.subTest(path=relative):
                self.assertEqual(project_document(relative), PROJECT_ROOT / relative)
        absolute = PROJECT_ROOT / "README.md"
        self.assertEqual(project_document(absolute), absolute)

    def test_custom_output_rebases_document_artifact_and_image_links(self) -> None:
        with tempfile.TemporaryDirectory(prefix="reports có khoảng trắng ") as directory:
            target = Path(directory) / "nested" / "report.md"
            sources = {
                "protocol": "MAIN_EXPERIMENTS_PROTOCOL_V2.md",
                "data": "docs/main_experiments_results/results.csv",
                "figure": "docs/main_experiments_results/figures/email-Eu-core_rumor_mean.png",
            }
            write_project_report(target, "\n".join(
                f"{'!' if label == 'figure' else ''}[{label}]({path})"
                for label, path in sources.items()
            ))
            for line, path in zip(target.read_text().splitlines(), sources.values()):
                link = line.split("](", 1)[1][:-1]
                self.assertEqual((target.parent / link).resolve(), project_document(path))

    def test_external_links_fragments_and_repository_commands_are_preserved(self) -> None:
        content = (
            "[site](https://example.com/report?q=1#results)\n"
            "[contact](mailto:research@example.com)\n"
            "[section](#results)\n"
            "[absolute](/shared/report.md)\n"
            "```sh\npython main.py experiment --config experiments/configs/runner_smoke_email.json\n```\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.md"
            write_project_report(target, content)
            self.assertEqual(target.read_text(), content)

    def test_relocated_link_keeps_query_and_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.md"
            write_project_report(target, "[protocol](MAIN_EXPERIMENTS_PROTOCOL_V2.md?view=1#frozen-design)")
            link = target.read_text().split("](", 1)[1][:-1]
            path, suffix = link.split("?", 1)
            self.assertEqual((target.parent / path).resolve(), project_document("MAIN_EXPERIMENTS_PROTOCOL_V2.md"))
            self.assertEqual(suffix, "view=1#frozen-design")


if __name__ == "__main__":
    unittest.main()
