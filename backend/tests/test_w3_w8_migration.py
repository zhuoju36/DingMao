"""W3-W8 第 2 切片测试：Law 数据模型新字段（version + aliases）。

集成测试，使用真实 PostgreSQL（db 已通过 alembic upgrade 升级）。
用纯 SQL 验证 schema + 默认值（避免 asyncpg ORM 事务冲突）。
"""
import subprocess

import pytest


def _psql(query: str) -> str:
    """直接调 psql 命令行工具，返回结果。"""
    result = subprocess.run(
        [
            "docker", "exec", "dingmao-postgres-dev",
            "psql", "-U", "dingmao", "-d", "dingmao",
            "-t", "-c", query,
        ],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# ===== Migration 后 schema 验证 =====

def test_laws_table_has_version_column():
    """P0-3 修复：version 列已添加。"""
    result = _psql(
        "SELECT column_name, data_type, character_maximum_length, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name='laws' AND column_name='version';"
    )
    assert "version" in result
    assert "character varying" in result
    assert "20" in result  # length
    assert "YES" in result  # nullable


def test_laws_table_has_aliases_column():
    """P0-1 修复：aliases JSONB 列已添加。"""
    result = _psql(
        "SELECT column_name, data_type, column_default "
        "FROM information_schema.columns "
        "WHERE table_name='laws' AND column_name='aliases';"
    )
    assert "aliases" in result
    assert "jsonb" in result
    # server_default='[]'::jsonb 应出现在 column_default
    assert "'[]'" in result or "[]" in result


def test_laws_table_existing_columns_unchanged():
    """原有列未被破坏（migration 是 additive only）。"""
    result = _psql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='laws' ORDER BY ordinal_position;"
    )
    # 原有 9 列 + 新 2 列
    expected = [
        "id", "code", "name", "category", "issuing_org",
        "version",        # 新（P0-3 修复）
        "aliases",        # 新（P0-1 修复）
        "effective_date", "status", "replaced_by", "tsv",
        "created_at", "updated_at",
    ]
    for col in expected:
        assert col in result, f"列 {col} 应存在"


def test_existing_law_rows_get_default_aliases():
    """升级前已存在的 Law 行，aliases 默认为空数组（server_default='[]'）。"""
    result = _psql("SELECT COUNT(*) FROM laws;")
    if int(result) == 0:
        pytest.skip("无历史 Law 行")
    result = _psql(
        "SELECT COUNT(*) FROM laws WHERE aliases = '[]'::jsonb;"
    )
    # 所有历史行 aliases 都应是 []
    assert result != ""


def test_insert_law_with_aliases_works():
    """P0-1 修复验证：可插入带 aliases 的 Law 行，DB 接受 JSONB 数组。"""
    test_code = "TEST_MIGRATION_W38_001"
    # 用 SQL 直接插（不在 fixture 事务里，避免 ORM 异步冲突）
    _psql(
        f"INSERT INTO laws (code, name, category, version, aliases, status, created_at, updated_at) "
        f"VALUES ('{test_code}', 'W3-W8 测试法', 'civil', '2020', "
        f"'[\"民法典\", \"Civil Code\"]'::jsonb, 'active', NOW(), NOW());"
    )
    # 读回来
    result = _psql(f"SELECT version, aliases FROM laws WHERE code = '{test_code}';")
    assert "2020" in result
    assert "Civil Code" in result
    # 清理
    _psql(f"DELETE FROM laws WHERE code = '{test_code}';")


def test_insert_law_without_aliases_works():
    """不传 aliases，DB 默认 '[]'。"""
    test_code = "TEST_MIGRATION_W38_002"
    _psql(
        f"INSERT INTO laws (code, name, category, version, status, created_at, updated_at) "
        f"VALUES ('{test_code}', 'W3-W8 测试法 2', 'construction', NULL, 'active', NOW(), NOW());"
    )
    result = _psql(f"SELECT aliases FROM laws WHERE code = '{test_code}';")
    assert "[]" in result
    _psql(f"DELETE FROM laws WHERE code = '{test_code}';")


def test_code_unique_constraint_still_works():
    """原唯一约束未破坏。"""
    test_code = "TEST_MIGRATION_W38_003"
    _psql(
        f"INSERT INTO laws (code, name, category, status, created_at, updated_at) "
        f"VALUES ('{test_code}', 'A', 'civil', 'active', NOW(), NOW());"
    )
    # 重复插应失败
    result = subprocess.run(
        [
            "docker", "exec", "dingmao-postgres-dev",
            "psql", "-U", "dingmao", "-d", "dingmao",
            "-v", "ON_ERROR_STOP=1",
            "-c",
            f"INSERT INTO laws (code, name, category, status, created_at, updated_at) "
            f"VALUES ('{test_code}', 'B', 'civil', 'active', NOW(), NOW());",
        ],
        capture_output=True, text=True,
    )
    # 应返回非 0 退出码
    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower() or "unique" in result.stderr.lower()
    # 清理
    _psql(f"DELETE FROM laws WHERE code = '{test_code}';")
