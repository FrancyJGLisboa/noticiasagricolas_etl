from pathlib import Path


def test_freshness_guard_precedes_all_publication_steps() -> None:
    workflow = Path(".github/workflows/daily-update.yml").read_text(encoding="utf-8")

    guard = workflow.index("- name: Validate critical data freshness")
    release = workflow.index("- name: Upload data to release")
    publication = workflow.index("- name: Publish CSVs and charts to data branch")

    assert guard < release < publication
