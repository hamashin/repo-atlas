import subprocess

import pytest

from atlas.publisher import AtlasWorkspace, PublishError, is_allowed_path


@pytest.mark.parametrize(
    "path,ok",
    [
        ("README.md", True),
        ("repos/demo/README.md", True),
        ("repos/demo/architecture.svg", True),
        ("repos/README.md", False),
        ("src/atlas/pipeline.py", False),
        ("install.sh", False),
        ("repos/../install.sh", False),
        ("/etc/passwd", False),
        (".github/workflows/x.yml", False),
    ],
)
def test_is_allowed_path(path, ok):
    assert is_allowed_path(path) is ok


def _workspace(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    (seed / "README.md").write_text("init\n")
    (seed / "install.sh").write_text("echo\n")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
    subprocess.run(["git", *env, "-C", str(seed), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD:main"], check=True)
    ws = AtlasWorkspace(
        tmp_path / "ws", str(remote), "main", tmp_path / "none", tmp_path / "none", "bot", "bot@example.com"
    )
    ws.sync()
    return ws, remote


def test_commit_and_push_allowed_only(tmp_path):
    ws, remote = _workspace(tmp_path)
    ws.write("repos/demo/README.md", "# demo\n")
    ws.write("README.md", "index\n")
    assert ws.commit_and_push("update", dry_run=False)
    log = subprocess.run(["git", "--git-dir", str(remote), "log", "--name-only", "-1", "--format="],
                         capture_output=True, text=True, check=True).stdout.split()
    assert sorted(log) == ["README.md", "repos/demo/README.md"]
    assert ws.commit_and_push("noop", dry_run=False) is False


def test_rejects_outside_changes(tmp_path):
    ws, _ = _workspace(tmp_path)
    (ws.path / "install.sh").write_text("rm -rf /\n")
    ws.write("repos/demo/README.md", "# demo\n")
    with pytest.raises(PublishError):
        ws.commit_and_push("update", dry_run=False)
    with pytest.raises(PublishError):
        ws.write("install.sh", "x")


def test_remove_repo_dir_stays_inside(tmp_path):
    ws, _ = _workspace(tmp_path)
    ws.write("repos/demo/README.md", "# demo\n")
    ws.remove_repo_dir("demo")
    assert ws.listed_names() == set()
    with pytest.raises(PublishError):
        ws.remove_repo_dir("..")
