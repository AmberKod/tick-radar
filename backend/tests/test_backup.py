import base64
import hashlib
import json
import sys
from unittest.mock import Mock

import pytest

pytest.importorskip("cryptography", reason="完整备份回归需要安装 backend[backup]")

from cross_market.operations import backup as b  # noqa: E402

DUMP = b"CREATE TABLE synthetic (id INT);\n"
IMAGE = "sha256:" + "a" * 64
CONTAINER = "b" * 64
HEADER = {
    "format": "TRBK001",
    "created_at": "2026-11-22T00:00:00+00:00",
    "source_database": "tick_radar",
    "mysql_image_id": IMAGE,
    "schema_revision": "0002",
    "dump_sha256": hashlib.sha256(DUMP).hexdigest(),
}


def key_and_archive(tmp_path):
    key = tmp_path / "secret" / "key"
    b.init_key(key)
    archive = tmp_path / "backup.trbk"
    b.publish_archive(archive, b.encrypt_archive(b.load_key(key), HEADER, DUMP))
    return key, archive


def test_exclusive_key_roundtrip_and_unique_nonce(tmp_path):
    key, archive = key_and_archive(tmp_path)
    first = archive.read_bytes()
    decoded = b.decrypt_archive(b.load_key(key), first)
    assert decoded.dump == DUMP and decoded.header == HEADER
    assert DUMP not in first
    assert first != b.encrypt_archive(b.load_key(key), HEADER, DUMP)
    with pytest.raises(b.BackupError):
        b.init_key(key)
    assert len(b.load_key(key)) == 32


@pytest.mark.parametrize("offset", [0, 8, 12, 30, -18, -1])
def test_tampered_archive_rejected(tmp_path, offset):
    key, archive = key_and_archive(tmp_path)
    altered = bytearray(archive.read_bytes())
    altered[offset] ^= 1
    with pytest.raises(b.BackupError):
        b.decrypt_archive(b.load_key(key), bytes(altered))


def test_wrong_key_truncation_and_invalid_headers(tmp_path):
    key, archive = key_and_archive(tmp_path)
    with pytest.raises(b.BackupError):
        b.decrypt_archive(b"x" * 32, archive.read_bytes())
    for source in (b"", b.MAGIC, archive.read_bytes()[:30], archive.read_bytes()[:-1]):
        with pytest.raises(b.BackupError):
            b.decrypt_archive(b.load_key(key), source)
    for header in (
        {},
        {**HEADER, "unexpected": "x"},
        {**HEADER, "mysql_image_id": "mysql:latest"},
        {**HEADER, "schema_revision": None},
        {**HEADER, "created_at": "2026-11-22"},
    ):
        with pytest.raises(b.BackupError):
            b.encrypt_archive(b.load_key(key), header, DUMP)


def test_bounded_archive_and_key_reads(tmp_path, monkeypatch):
    key, archive = key_and_archive(tmp_path)
    monkeypatch.setattr(b, "MAX_ARCHIVE_BYTES", 20)
    with pytest.raises(b.BackupError):
        b._read_archive(archive)
    key.write_bytes(b"x" * 100)
    with pytest.raises(b.BackupError):
        b.load_key(key)
    key.write_bytes(base64.b64encode(b"k" * 32))
    assert b.load_key(key) == b"k" * 32


def test_dump_limit_empty_and_hash_validation(monkeypatch):
    monkeypatch.setattr(b, "MAX_DUMP_BYTES", 10)
    for dump in (b"", b"x" * 11):
        with pytest.raises(b.BackupError):
            b.encrypt_archive(b"k" * 32, HEADER, dump)
    with pytest.raises(b.BackupError):
        b.encrypt_archive(b"k" * 32, HEADER, b"wrong")


def test_publish_exclusive_and_failure_leaves_no_partial(tmp_path, monkeypatch):
    target = tmp_path / "archive.trbk"
    encrypted = b.encrypt_archive(b"k" * 32, HEADER, DUMP)
    b.publish_archive(target, encrypted)
    with pytest.raises(b.BackupError):
        b.publish_archive(target, b"replacement")
    assert target.read_bytes() == encrypted
    assert list(tmp_path.glob(".backup-*")) == []
    monkeypatch.setattr(b.os, "link", Mock(side_effect=OSError("private path")))
    failed = tmp_path / "failed.trbk"
    with pytest.raises(b.BackupError) as caught:
        b.publish_archive(failed, encrypted)
    assert "private path" not in str(caught.value)
    assert not failed.exists() and list(tmp_path.glob(".backup-*")) == []


def test_bad_auth_does_not_call_docker(tmp_path):
    key, archive = key_and_archive(tmp_path)
    key.write_bytes(b"z" * 32)
    runner = Mock()
    with pytest.raises(b.BackupError):
        b.restore_check(key, archive, runner)
    runner.run.assert_not_called()


class SourceRunner:
    def __init__(self, engine="InnoDB", revision_changes=False):
        self.calls = []
        self.engine = engine
        self.revision_changes = revision_changes
        self.revisions = 0

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "ps":
            assert "label=com.docker.compose.project=tick-radar" in args
            assert "label=com.docker.compose.service=mysql" in args
            return CONTAINER[:12].encode()
        if args[0] == "inspect":
            return IMAGE.encode()
        if args[-1] == 'printf "%s" "$MYSQL_DATABASE"':
            return b"tick_radar"
        if args[-1] == b.SOURCE_DUMP:
            assert kwargs["max_bytes"] == b.MAX_DUMP_BYTES
            return DUMP
        query = kwargs.get("input_data", b"").decode()
        if query == b.TABLE_QUERY:
            return f"synthetic\t{self.engine}\tBASE TABLE".encode()
        if query == b.UNSUPPORTED_QUERY:
            return b"0"
        if "version_num" in query:
            self.revisions += 1
            return b"0003" if self.revision_changes and self.revisions > 1 else b"0002"
        raise AssertionError(args)


def test_create_uses_container_environment_and_exclusive_encrypted_output(tmp_path):
    key = tmp_path / "keys" / "key"
    b.init_key(key)
    runner = SourceRunner()
    target = b.create_backup(key, tmp_path / "archives", runner)
    assert b.inspect_archive(key, target)["dump_sha256"] == HEADER["dump_sha256"]
    assert DUMP not in target.read_bytes()
    commands = json.dumps([args for args, _ in runner.calls])
    assert ".Config.Env" not in commands and "MYSQL_PASSWORD=" not in commands
    assert "--databases" not in b.SOURCE_DUMP


@pytest.mark.parametrize("engine,changes", [("MyISAM", False), ("InnoDB", True)])
def test_unsupported_engine_or_schema_change_does_not_publish(tmp_path, engine, changes):
    key = tmp_path / "key"
    b.init_key(key)
    target = tmp_path / "archives"
    with pytest.raises(b.BackupError):
        b.create_backup(key, target, SourceRunner(engine, changes))
    assert not target.exists()


def test_missing_or_ambiguous_source_rejected():
    for output in (b"", b"abc123abc123\ndef456def456"):
        runner = Mock()
        runner.run.return_value = output
        with pytest.raises(b.BackupError):
            b._find_source(runner)
        assert runner.run.call_count == 1


class RestoreRunner:
    def __init__(self, fail_at=None, wrong_owner=False):
        self.calls = []
        self.fail_at = fail_at
        self.wrong_owner = wrong_owner
        self.name = self.owner = None

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "create":
            self.name = args[args.index("--name") + 1]
            self.owner = args[args.index("--label") + 1].split("=", 1)[1]
            assert args[args.index("--network") + 1] == "none"
            assert "-p" not in args and "--publish" not in args and "--volume" not in args
            secret = kwargs["environment"]["MYSQL_ROOT_PASSWORD"]
            assert secret not in " ".join(args)
            if self.fail_at == "create":
                raise b.BackupError("client timeout")
            return CONTAINER.encode()
        if args[0] == "ps":
            return CONTAINER[:12].encode()
        if args[0] == "inspect":
            owner = "other" if self.wrong_owner else self.owner
            return f"{CONTAINER} {owner} /{self.name}".encode()
        if args[0] == "rm":
            assert args == ["rm", "-f", "-v", CONTAINER]
            return CONTAINER.encode()
        if args[0] == "start":
            return CONTAINER.encode()
        if args[-1] == b.RESTORE_DUMP:
            return DUMP
        data = kwargs.get("input_data", b"")
        if data == DUMP:
            if self.fail_at == "import":
                raise b.BackupError("import failed")
            return b""
        if data == b"SELECT 1;":
            return b"1"
        if b"version_num" in data:
            return b"0002"
        if data.decode() == b.TABLE_QUERY:
            return b"synthetic\tInnoDB\tBASE TABLE"
        if b"COUNT(*)" in data:
            return b"3"
        if b"VERSION()" in data:
            return b"8.4.test"
        raise AssertionError(args)


def test_restore_authenticates_before_docker_and_redump_matches(tmp_path):
    key, archive = key_and_archive(tmp_path)
    runner = RestoreRunner()
    result = b.restore_check(key, archive, runner)
    assert result["success"] and result["redump_sha256_match"]
    assert result["cleanup"] == "removed" and result["host_ports"] == []
    assert result["table_counts"] == {"synthetic": 3}
    assert runner.calls[0][0][0] == "create" and runner.calls[-1][0][0] == "rm"


@pytest.mark.parametrize("stage", ["create", "import"])
def test_restore_failure_cleans_only_owned_container(tmp_path, stage):
    key, archive = key_and_archive(tmp_path)
    runner = RestoreRunner(fail_at=stage)
    with pytest.raises(b.BackupError):
        b.restore_check(key, archive, runner)
    assert runner.calls[-1][0] == ["rm", "-f", "-v", CONTAINER]


def test_restore_refuses_cleanup_when_owner_does_not_match(tmp_path):
    key, archive = key_and_archive(tmp_path)
    runner = RestoreRunner(wrong_owner=True)
    with pytest.raises(b.BackupError, match="清理失败"):
        b.restore_check(key, archive, runner)
    assert all(args[0] != "rm" for args, _ in runner.calls)


def test_key_cannot_share_backup_directory_tree(tmp_path):
    key = tmp_path / "archives" / "key"
    b.init_key(key)
    with pytest.raises(b.BackupError):
        b.create_backup(key, tmp_path / "archives", Mock())


def test_runner_streams_in_memory_and_bounds_output():
    runner = b.DockerRunner(sys.executable)
    assert (
        runner.run(
            ["-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            input_data=b"synthetic",
            max_bytes=20,
        )
        == b"synthetic"
    )
    with pytest.raises(b.BackupError, match="超过"):
        runner.run(["-c", "import sys; sys.stdout.buffer.write(b'x'*1000000)"], max_bytes=50)


def test_runner_timeout_and_errors_do_not_leak_stderr():
    runner = b.DockerRunner(sys.executable)
    with pytest.raises(b.BackupError, match="超时"):
        runner.run(["-c", "import time; time.sleep(10)"], timeout=0.1)
    with pytest.raises(b.BackupError) as caught:
        runner.run(["-c", "import sys; sys.stderr.write('private-password'); sys.exit(2)"])
    assert "private-password" not in str(caught.value)
