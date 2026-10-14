-- Supabase SQL Editor で実行してテーブルを作成する
-- 実行順序: このファイルを上から順にすべて実行

-- UUID生成用の拡張機能を有効化
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- survey_groups: グループ単位の調査記録
-- ============================================================
CREATE TABLE survey_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    location TEXT NOT NULL,
    survey_type TEXT NOT NULL CHECK (survey_type IN ('pretest', 'main')),
    input_method TEXT NOT NULL CHECK (input_method IN ('field', 'transcription')),
    group_size INTEGER NOT NULL CHECK (group_size >= 1 AND group_size <= 6),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    session_draft JSONB
);

-- ============================================================
-- responses: メンバーごとの回答ヘッダ
-- ============================================================
CREATE TABLE responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id UUID NOT NULL REFERENCES survey_groups(id) ON DELETE RESTRICT,
    member_number INTEGER NOT NULL CHECK (member_number >= 1),
    conformity_flag BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    branch TEXT CHECK (branch IN ('A', 'B'))
);

-- ============================================================
-- answers: 個々の回答値
-- ============================================================
CREATE TABLE answers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    response_id UUID NOT NULL REFERENCES responses(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL,
    value TEXT,
    values TEXT[]
);

-- ============================================================
-- edit_history: 変更履歴
-- ============================================================
CREATE TABLE edit_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_type TEXT NOT NULL CHECK (target_type IN ('group', 'response', 'answer')),
    target_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete', 'restore')),
    old_value JSONB,
    new_value JSONB,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by TEXT NOT NULL DEFAULT 'surveyor'
);

-- ============================================================
-- classifications: 自由記述の分類結果
-- ============================================================
CREATE TABLE classifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    answer_id UUID NOT NULL REFERENCES answers(id) ON DELETE RESTRICT,
    categories TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('classified', 'pending', 'new_category')) DEFAULT 'classified',
    memo TEXT,
    classifier_id TEXT NOT NULL DEFAULT 'classifier_1',
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- インデックス
-- ============================================================
CREATE INDEX idx_responses_group_id ON responses(group_id);
CREATE INDEX idx_answers_response_id ON answers(response_id);
CREATE INDEX idx_answers_question_id ON answers(question_id);
CREATE INDEX idx_edit_history_target ON edit_history(target_type, target_id);
CREATE INDEX idx_classifications_answer_id ON classifications(answer_id);
CREATE INDEX idx_survey_groups_not_deleted ON survey_groups(created_at) WHERE NOT is_deleted;

-- ============================================================
-- RLS (Row Level Security) ポリシー
-- Supabase の anon キーでの読み書きを許可
-- ============================================================
ALTER TABLE survey_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE edit_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE classifications ENABLE ROW LEVEL SECURITY;

-- anon ロールに全操作を許可（アプリ側でパスワード認証するため）
CREATE POLICY "Allow all for anon" ON survey_groups FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON responses FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON answers FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON edit_history FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON classifications FOR ALL USING (true) WITH CHECK (true);
