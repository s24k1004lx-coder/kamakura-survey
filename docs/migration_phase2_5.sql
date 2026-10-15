-- Phase 2.5（調査記録機能）用マイグレーション
-- 既存のDBに対して Supabase SQL Editor で一度だけ実行する
-- （新規構築の場合は setup_tables.sql に含まれているので不要）
-- 何度実行しても壊れないよう IF NOT EXISTS / DROP IF EXISTS で書いている

-- ============================================================
-- survey_groups: 所要時間・つまずきフラグ
-- ============================================================
-- started_at  : 「入力開始」を押した時刻
-- saved_at    : 「保存する」を押した時刻
-- duration_sec: saved_at - started_at（秒）
-- stumble_flags: つまずきフラグ {"設問ID": "メモ（空文字可）"}
ALTER TABLE survey_groups ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE survey_groups ADD COLUMN IF NOT EXISTS saved_at TIMESTAMPTZ;
ALTER TABLE survey_groups ADD COLUMN IF NOT EXISTS duration_sec INTEGER CHECK (duration_sec >= 0);
ALTER TABLE survey_groups ADD COLUMN IF NOT EXISTS stumble_flags JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ============================================================
-- responses: 回答方式（調査員が読み上げ / 本人が記入）
-- ============================================================
ALTER TABLE responses ADD COLUMN IF NOT EXISTS response_mode TEXT
    CHECK (response_mode IN ('interviewer', 'self'));

-- ============================================================
-- refusals: 声かけして断られた記録（1行 = 1回の断り）
-- 「1つ戻す」は論理削除で行う
-- ============================================================
CREATE TABLE IF NOT EXISTS refusals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    location TEXT NOT NULL,
    survey_type TEXT NOT NULL CHECK (survey_type IN ('pretest', 'main')),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_refusals_created_at ON refusals(created_at) WHERE NOT is_deleted;

-- ============================================================
-- survey_day_notes: 調査日メモ（1日1行）
-- ============================================================
CREATE TABLE IF NOT EXISTS survey_day_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    survey_date DATE NOT NULL UNIQUE,
    weather TEXT,
    crowd TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- edit_history: 新しい記録種別を履歴対象に追加
-- ============================================================
ALTER TABLE edit_history DROP CONSTRAINT IF EXISTS edit_history_target_type_check;
ALTER TABLE edit_history ADD CONSTRAINT edit_history_target_type_check
    CHECK (target_type IN ('group', 'response', 'answer', 'refusal', 'day_note'));

-- ============================================================
-- RLS
-- ============================================================
ALTER TABLE refusals ENABLE ROW LEVEL SECURITY;
ALTER TABLE survey_day_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for anon" ON refusals;
DROP POLICY IF EXISTS "Allow all for anon" ON survey_day_notes;
CREATE POLICY "Allow all for anon" ON refusals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON survey_day_notes FOR ALL USING (true) WITH CHECK (true);
