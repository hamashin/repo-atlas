import io
import tarfile

from atlas.collector import SourceCollector
from atlas.sanitizer import PathFilter, Sanitizer


def _tarball(tmp_path, files):
    path = tmp_path / "src.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"owner-repo-abc123/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_collect_excludes_and_masks(tmp_path):
    tar = _tarball(
        tmp_path,
        {
            "README.md": "# demo\n接続先は 192.0.2.5 です",
            ".env": "SECRET=should-not-appear",
            "keys/server.key": "PRIVATE",
            "src/main.py": "print('hello')\n",
            "image.png": "\0\0binary",
        },
    )
    work = tmp_path / "work"
    work.mkdir()
    result = SourceCollector(PathFilter(), Sanitizer(), 10000).collect(tar, work)
    paths = [p for p, _ in result.documents]
    assert paths[0] == "README.md"
    assert "src/main.py" in paths
    assert all(".env" not in p and "server.key" not in p for p in result.tree)
    text = result.as_prompt()
    assert "should-not-appear" not in text
    assert "192.0.2.5" not in text and "[IP]" in text


def test_collect_respects_budget(tmp_path):
    tar = _tarball(tmp_path, {f"src/m{i}.py": "x = 1\n" * 500 for i in range(20)})
    work = tmp_path / "work"
    work.mkdir()
    result = SourceCollector(PathFilter(), Sanitizer(), 8000).collect(tar, work)
    assert len(result.as_prompt()) < 9000
    assert result.truncated
