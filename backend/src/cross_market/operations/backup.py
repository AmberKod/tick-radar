"""按需加密备份；恢复验收只允许新建隔离容器，不覆盖业务数据库。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"TRBK001\0"
KEY_BYTES = 32
NONCE_BYTES = 12
MAX_DUMP_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_ARCHIVE_BYTES = MAX_DUMP_BYTES + MAX_HEADER_BYTES + 40
DEFAULT_KEY = Path(".local-secrets/backup.key")
DEFAULT_OUTPUT = Path("artifacts/backups")
OWNER_LABEL = "io.tickradar.backup-owner"
HEADER_FIELDS = {
    "format",
    "created_at",
    "source_database",
    "mysql_image_id",
    "schema_revision",
    "dump_sha256",
}
DUMP_OPTIONS = (
    "--single-transaction --quick --skip-lock-tables --no-tablespaces "
    "--set-gtid-purged=OFF --column-statistics=0 --hex-blob --skip-comments "
    "--skip-dump-date --order-by-primary --skip-add-locks --skip-extended-insert"
)
# 脚本固定，密码只由容器环境展开；宿主参数中没有凭据值。
SOURCE_DUMP = (
    'export MYSQL_PWD="$MYSQL_PASSWORD"; exec mysqldump -u"$MYSQL_USER" '
    + DUMP_OPTIONS
    + ' "$MYSQL_DATABASE"'
)
RESTORE_DUMP = (
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysqldump -uroot '
    + DUMP_OPTIONS
    + " tick_radar_restore"
)
SOURCE_SQL = (
    'export MYSQL_PWD="$MYSQL_PASSWORD"; exec mysql --batch --raw '
    '--skip-column-names -u"$MYSQL_USER" "$MYSQL_DATABASE"'
)
RESTORE_SQL = (
    'test "$(cat /proc/1/comm)" = "mysqld" || exit 1; '
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --binary-mode '
    "--local-infile=0 --batch --raw --skip-column-names -uroot tick_radar_restore"
)
TABLE_QUERY = (
    "SELECT TABLE_NAME,ENGINE,TABLE_TYPE FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME;"
)
UNSUPPORTED_QUERY = (
    "SELECT (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE())"
    "+(SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE())"
    "+(SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE());"
)


class BackupError(Exception):
    """仅包含可公开的操作摘要，不携带 SQL、密码或 Docker 错误原文。"""


@dataclass(frozen=True)
class Archive:
    header: dict[str, str]
    dump: bytes
    dump_sha256: str


def _image_id(value: str) -> str:
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise BackupError("源镜像身份无效")
    return value


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8").strip()
    except UnicodeError:
        raise BackupError("Docker 返回格式无效") from None


def load_key(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read(97)
    except OSError:
        raise BackupError("无法读取备份密钥") from None
    if len(raw) == KEY_BYTES:
        return raw
    try:
        decoded = base64.b64decode(raw, validate=True)
    except ValueError:
        raise BackupError("备份密钥格式无效") from None
    if len(decoded) != KEY_BYTES:
        raise BackupError("备份密钥长度无效")
    return decoded


def init_key(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(KEY_BYTES))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise BackupError("备份密钥已存在，拒绝覆盖") from None
    except OSError:
        raise BackupError("无法初始化备份密钥") from None


def _header_bytes(header: dict[str, str]) -> bytes:
    if not isinstance(header, dict) or set(header) != HEADER_FIELDS:
        raise BackupError("归档元数据字段无效")
    if not all(isinstance(value, str) and len(value) <= 256 for value in header.values()):
        raise BackupError("归档元数据类型无效")
    if header["format"] != "TRBK001":
        raise BackupError("归档版本不支持")
    _image_id(header["mysql_image_id"])
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", header["source_database"]):
        raise BackupError("归档数据库标识无效")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", header["schema_revision"]):
        raise BackupError("归档迁移版本无效")
    if not re.fullmatch(r"[a-f0-9]{64}", header["dump_sha256"]):
        raise BackupError("归档摘要无效")
    try:
        if datetime.fromisoformat(header["created_at"]).tzinfo is None:
            raise ValueError
        encoded = json.dumps(
            header, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    except (ValueError, UnicodeError):
        raise BackupError("归档时间或编码无效") from None
    if len(encoded) > MAX_HEADER_BYTES:
        raise BackupError("归档元数据超限")
    return encoded


def encrypt_archive(key: bytes, header: dict[str, str], dump: bytes) -> bytes:
    if len(key) != KEY_BYTES or not 0 < len(dump) <= MAX_DUMP_BYTES:
        raise BackupError("密钥长度或 SQL 大小无效（上限64MiB）")
    if hashlib.sha256(dump).hexdigest() != header.get("dump_sha256"):
        raise BackupError("SQL 与元数据摘要不匹配")
    raw = _header_bytes(header)
    prefix = MAGIC + len(raw).to_bytes(4, "big") + raw
    nonce = secrets.token_bytes(NONCE_BYTES)
    return prefix + nonce + AESGCM(key).encrypt(nonce, dump, prefix)


def decrypt_archive(key: bytes, source: bytes) -> Archive:
    if len(key) != KEY_BYTES or len(source) > MAX_ARCHIVE_BYTES:
        raise BackupError("密钥或归档大小无效")
    if len(source) < 41 or source[:8] != MAGIC:
        raise BackupError("归档格式无效")
    length = int.from_bytes(source[8:12], "big")
    end = 12 + length
    if not 1 <= length <= MAX_HEADER_BYTES or len(source) <= end + NONCE_BYTES + 16:
        raise BackupError("归档截断或元数据长度无效")
    try:
        header = json.loads(source[12:end])
    except (ValueError, UnicodeError, RecursionError):
        raise BackupError("归档元数据无效") from None
    _header_bytes(header)
    ciphertext = source[end + NONCE_BYTES :]
    if len(ciphertext) - 16 > MAX_DUMP_BYTES:
        raise BackupError("SQL 超过64MiB限制")
    try:
        dump = AESGCM(key).decrypt(source[end : end + NONCE_BYTES], ciphertext, source[:end])
    except InvalidTag:
        raise BackupError("归档认证失败：密钥错误或文件损坏") from None
    digest = hashlib.sha256(dump).hexdigest()
    if digest != header["dump_sha256"]:
        raise BackupError("归档 SQL 摘要不一致")
    return Archive(header, dump, digest)


def _read_archive(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            source = stream.read(MAX_ARCHIVE_BYTES + 1)
    except OSError:
        raise BackupError("无法读取备份文件") from None
    if len(source) > MAX_ARCHIVE_BYTES:
        raise BackupError("备份文件超过大小限制")
    return source


def publish_archive(output: Path, archive: bytes) -> None:
    stage = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=".backup-", delete=False
        ) as stream:
            stage = Path(stream.name)
            stream.write(archive)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(stage, 0o600)
        os.link(stage, output)
    except FileExistsError:
        raise BackupError("备份文件已存在，拒绝覆盖") from None
    except OSError:
        raise BackupError("备份发布失败，文件系统须支持排他硬链接") from None
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


class DockerRunner:
    def __init__(self, executable: str = "docker"):
        self.executable = executable

    def run(
        self,
        args: Sequence[str],
        *,
        input_data: bytes | None = None,
        timeout: float = 30,
        environment: dict[str, str] | None = None,
        max_bytes: int = 65_536,
    ) -> bytes:
        """有界管道读取；任何 Docker stdout（含明文 SQL）均不写临时磁盘。"""
        buffer = io.BytesIO()
        overflow = threading.Event()
        reader_failed = threading.Event()
        writer_failed = threading.Event()
        try:
            process = subprocess.Popen(
                [self.executable, *args],
                stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,  # 原始管道关闭不等待其他读取线程持有的缓冲锁。
                shell=False,
                env=environment,
            )
        except OSError:
            raise BackupError("Docker 命令不可用") from None

        def read_output():
            try:
                while chunk := process.stdout.read(65_536):
                    remaining = max_bytes - buffer.tell()
                    if len(chunk) > remaining:
                        overflow.set()
                        process.kill()
                        return
                    buffer.write(chunk)
            except (OSError, ValueError):
                reader_failed.set()

        def write_input():
            try:
                # 原始管道允许部分写入，必须逐块写完再关闭。
                remaining = memoryview(input_data)
                while remaining:
                    written = process.stdin.write(remaining[:65_536])
                    if not written:
                        raise BrokenPipeError
                    remaining = remaining[written:]
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                writer_failed.set()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        writer = None
        if input_data is not None:
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.kill()
                    break
                overflow.wait(0.05)
                if overflow.is_set():
                    break
            process.wait(timeout=5)
            reader.join(timeout=5)
            if writer is not None:
                writer.join(timeout=5)
            if timed_out:
                raise BackupError("Docker 操作超时")
            if overflow.is_set():
                raise BackupError("Docker 输出超过大小限制")
            if (
                reader_failed.is_set()
                or writer_failed.is_set()
                or reader.is_alive()
                or (writer and writer.is_alive())
            ):
                raise BackupError("Docker 管道读取失败")
            if process.returncode != 0:
                raise BackupError(f"Docker 操作失败（退出码{process.returncode}）")
            return buffer.getvalue()
        except subprocess.TimeoutExpired:
            process.kill()
            raise BackupError("Docker 进程未能及时结束") from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            if process.stdin:
                process.stdin.close()


def _sql(runner: DockerRunner, container: str, query: str, *, restored: bool = False) -> str:
    script = RESTORE_SQL if restored else SOURCE_SQL
    return _text(
        runner.run(
            ["exec", "-i", container, "sh", "-c", script], input_data=query.encode(), timeout=20
        )
    )


def _find_source(runner: DockerRunner) -> tuple[str, str, str]:
    candidates = _text(
        runner.run(
            [
                "ps",
                "--filter",
                "label=com.docker.compose.project=tick-radar",
                "--filter",
                "label=com.docker.compose.service=mysql",
                "--format",
                "{{.ID}}",
            ]
        )
    ).splitlines()
    if len(candidates) != 1 or not re.fullmatch(r"[a-f0-9]{12,64}", candidates[0]):
        raise BackupError("必须恰有一个运行中的 tick-radar MySQL 容器")
    container = candidates[0]
    image = _image_id(_text(runner.run(["inspect", "--format", "{{.Image}}", container])))
    database = _text(runner.run(["exec", container, "sh", "-c", 'printf "%s" "$MYSQL_DATABASE"']))
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
        raise BackupError("源数据库名称无效")
    return container, image, database


def _source_schema(runner: DockerRunner, container: str) -> tuple[str, str]:
    tables = _sql(runner, container, TABLE_QUERY)
    if not tables:
        raise BackupError("源数据库无业务表")
    for line in tables.splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or fields[1:] != ["InnoDB", "BASE TABLE"]:
            raise BackupError("当前仅支持 InnoDB 基础表，不支持视图或其他表引擎")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", fields[0]):
            raise BackupError("表名超出本工具支持范围")
    if _sql(runner, container, UNSUPPORTED_QUERY) != "0":
        raise BackupError("当前不支持包含触发器、例程或事件的数据库")
    revision = _sql(runner, container, "SELECT version_num FROM alembic_version;")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", revision):
        raise BackupError("迁移版本缺失或不受支持")
    return tables, revision


def create_backup(key_path: Path, output_dir: Path, runner: DockerRunner | None = None) -> Path:
    key = load_key(key_path)
    if key_path.resolve().is_relative_to(output_dir.resolve()):
        raise BackupError("密钥不得与备份文件放在同一目录树")
    runner = runner or DockerRunner()
    container, image, database = _find_source(runner)
    before = _source_schema(runner, container)
    dump = runner.run(
        ["exec", container, "sh", "-c", SOURCE_DUMP], timeout=90, max_bytes=MAX_DUMP_BYTES
    )
    if not dump or _source_schema(runner, container) != before:
        raise BackupError("导出为空或期间结构发生变化；备份期间请停止 DDL 迁移")
    header = {
        "format": "TRBK001",
        "created_at": datetime.now(UTC).isoformat(),
        "source_database": database,
        "mysql_image_id": image,
        "schema_revision": before[1],
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
    }
    target = output_dir / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ") + ".trbk")
    publish_archive(target, encrypt_archive(key, header, dump))
    return target


def _remove_owned(runner: DockerRunner, name: str, owner: str) -> str:
    # 创建命令可能超时：按唯一名称和 owner 找回，而不是依赖已返回的容器 ID。
    raw = _text(
        runner.run(
            [
                "ps",
                "-a",
                "--filter",
                f"name=^/{name}$",
                "--filter",
                f"label={OWNER_LABEL}={owner}",
                "--format",
                "{{.ID}}",
            ]
        )
    )
    if not raw:
        return "not-created"
    if not re.fullmatch(r"[a-f0-9]{12,64}", raw):
        raise BackupError("恢复容器清理身份不唯一")
    actual = _text(
        runner.run(
            [
                "inspect",
                "--format",
                '{{.Id}} {{index .Config.Labels "' + OWNER_LABEL + '"}} {{.Name}}',
                raw,
            ]
        )
    ).split()
    if len(actual) != 3 or actual[1:] != [owner, "/" + name]:
        raise BackupError("恢复容器所有权不匹配，拒绝清理")
    runner.run(["rm", "-f", "-v", actual[0]], timeout=30)
    return "removed"


def restore_check(key_path: Path, archive_path: Path, runner: DockerRunner | None = None) -> dict:
    # 必须先验证整个密文，再创建临时实例或执行任何 SQL。
    archive = decrypt_archive(load_key(key_path), _read_archive(archive_path))
    runner = runner or DockerRunner()
    owner = uuid4().hex
    name = "tick-radar-restore-check-" + owner
    password = secrets.token_urlsafe(32)
    result = None
    attempted = False
    try:
        attempted = True
        container = _text(
            runner.run(
                [
                    "create",
                    "--name",
                    name,
                    "--label",
                    f"{OWNER_LABEL}={owner}",
                    "--network",
                    "none",
                    "--memory",
                    "1g",
                    "--cpus",
                    "1",
                    "--pids-limit",
                    "256",
                    "--tmpfs",
                    "/var/lib/mysql:rw,size=512m",
                    "--env",
                    "MYSQL_ROOT_PASSWORD",
                    "--env",
                    "MYSQL_DATABASE=tick_radar_restore",
                    archive.header["mysql_image_id"],
                    "--skip-networking",
                    "--mysqlx=0",
                ],
                environment={**os.environ, "MYSQL_ROOT_PASSWORD": password},
                timeout=30,
            )
        )
        if not re.fullmatch(r"[a-f0-9]{12,64}", container):
            raise BackupError("临时恢复容器 ID 无效")
        runner.run(["start", container])
        deadline = time.monotonic() + 90
        ready = False
        while time.monotonic() < deadline:
            try:
                ready = _sql(runner, container, "SELECT 1;", restored=True) == "1"
                if ready:
                    break
            except BackupError:
                pass
            threading.Event().wait(0.5)
        if not ready:
            raise BackupError("临时 MySQL 未能在90秒内就绪")
        runner.run(
            ["exec", "-i", container, "sh", "-c", RESTORE_SQL], input_data=archive.dump, timeout=90
        )
        revision = _sql(
            runner, container, "SELECT version_num FROM alembic_version;", restored=True
        )
        if revision != archive.header["schema_revision"]:
            raise BackupError("恢复后的迁移版本不匹配")
        recreated = runner.run(
            ["exec", container, "sh", "-c", RESTORE_DUMP], timeout=90, max_bytes=MAX_DUMP_BYTES
        )
        if hashlib.sha256(recreated).hexdigest() != archive.dump_sha256:
            raise BackupError("恢复后的 SQL 摘要不匹配")
        tables = _sql(runner, container, TABLE_QUERY, restored=True)
        counts = {}
        for line in tables.splitlines():
            table = line.split("\t")[0]
            if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", table):
                raise BackupError("恢复表名超出支持范围")
            counts[table] = int(
                _sql(runner, container, f"SELECT COUNT(*) FROM `{table}`;", restored=True)
            )
        result = {
            "success": True,
            "restored_mysql_version": _sql(runner, container, "SELECT VERSION();", restored=True),
            "revision": revision,
            "table_counts": counts,
            "dump_sha256": archive.dump_sha256,
            "redump_sha256_match": True,
            "network": "none",
            "host_ports": [],
        }
    finally:
        if attempted:
            try:
                cleanup = _remove_owned(runner, name, owner)
            except BackupError:
                raise BackupError(f"临时恢复容器清理失败，请检查 {name}") from None
    if result is None:
        raise BackupError("恢复未完成")
    result["cleanup"] = cleanup
    return result


def inspect_archive(key_path: Path, archive_path: Path) -> dict:
    archive = decrypt_archive(load_key(key_path), _read_archive(archive_path))
    return {
        "authenticated": True,
        "header": archive.header,
        "dump_bytes": len(archive.dump),
        "dump_sha256": archive.dump_sha256,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-key")
    create = commands.add_parser("create")
    create.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    for name in ("restore-check", "inspect"):
        commands.add_parser(name).add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init-key":
            init_key(args.key)
            print("备份密钥已生成，未输出；请另行安全保管。")
        elif args.command == "create":
            print(
                json.dumps(
                    {"archive": str(create_backup(args.key, args.output))}, ensure_ascii=True
                )
            )
        elif args.command == "restore-check":
            print(json.dumps(restore_check(args.key, args.archive), ensure_ascii=True))
        else:
            print(json.dumps(inspect_archive(args.key, args.archive), ensure_ascii=True))
    except (BackupError, OSError) as exc:
        message = str(exc) if isinstance(exc, BackupError) else "文件操作失败"
        parser.exit(2, f"备份操作失败：{message}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
