from pathlib import Path
from agent.config import REPO_ROOT

def read_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()

def write_file(relative_path: str, content: str) -> None:
    path = REPO_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

def list_directory(relative_path: str = ".") -> list[str]:
    base = REPO_ROOT / relative_path
    return [str(p.relative_to(REPO_ROOT)) for p in base.rglob("*") if p.is_file()]