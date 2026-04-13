from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_and_docs_have_no_workspace_absolute_links() -> None:
    targets = [REPO_ROOT / 'README.md', REPO_ROOT / 'README.en.md', *(REPO_ROOT / 'docs').rglob('*.md')]
    for path in targets:
        text = path.read_text()
        assert '/Users/dalizhou/Desktop/new_validation_agent/' not in text, str(path)


def test_packaging_assets_exist() -> None:
    required = [
        REPO_ROOT / 'LICENSE',
        REPO_ROOT / 'README.en.md',
        REPO_ROOT / 'agents' / 'vintage_programmer' / 'soul.md',
        REPO_ROOT / 'agents' / 'vintage_programmer' / 'identity.md',
        REPO_ROOT / 'agents' / 'vintage_programmer' / 'agent.md',
        REPO_ROOT / 'agents' / 'vintage_programmer' / 'tools.md',
    ]
    for path in required:
        assert path.exists(), str(path)
