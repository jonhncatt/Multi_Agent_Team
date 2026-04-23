from __future__ import annotations

from typing import Any


SUPPORTED_LOCALES: tuple[str, ...] = ("zh-CN", "ja-JP", "en")

_LOCALE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-hans-cn": "zh-CN",
    "ja": "ja-JP",
    "ja-jp": "ja-JP",
    "jp": "ja-JP",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "error.request_failed": "请求失败，请稍后重试。",
        "error.rate_limit": "模型提供方限流，请稍后重试。",
        "error.auth": "认证失败，请检查 OpenRouter / OpenAI-compatible key。",
        "error.upstream": "模型提供方暂时不可用，请稍后重试。",
        "error.request_failed_detail": "请求失败，请稍后重试或查看错误详情。",
        "health.permission_summary.full_filesystem": "full filesystem access enabled",
        "health.permission_summary.allowed_roots": "{count} allowed roots: {root_names}",
        "runtime.style.short": "回答尽量简短，先给结论，再给最多 3 条关键点。",
        "runtime.style.normal": "回答清晰、可执行，避免冗长。",
        "runtime.style.long": "回答可以更详细，但保持结构化，优先给行动建议。",
        "runtime.system.language_instruction": "默认使用简洁自然的中文回答；如果用户明确使用其他语言或要求翻译，再切换语言。",
        "runtime.system.output_requirements": "输出要求: 不输出思维链；不要虚构事实；不确定时明确说明；若已经使用工具，结论要基于工具结果。",
        "runtime.system.inline_message_analysis": "当用户直接在消息里粘贴代码、XML、HTML、JSON、YAML 或长文本时，应先就地分析当前消息内容，不要默认追问 workspace 路径。",
        "runtime.system.inline_error_analysis": "当用户贴出报错、代码片段、配置文本或日志时，默认把这些内容当作本轮要分析的对象；只有用户明确要求查看仓库文件、目录、网页或执行命令时，才优先调用工具。",
        "runtime.system.attachment_context": "如果 runtime_context_json 里已经给出 attachments 的 name/path，就把它们视为当前轮已提供上下文，不要先否认附件或要求用户重新描述路径。",
        "runtime.system.focus_context": "如果 runtime_context_json.current_task_focus 里已经给出 goal/cwd/active_files/active_attachments，就把它们当作当前任务的硬上下文继续推进；不要重复声称不知道目录、文件或附件。",
        "runtime.system.thread_memory": "如果 runtime_context_json.thread_memory.recent_tasks 或 recalled_context 里已经给出近期任务/附件回忆结果，回答“刚刚让我做什么”“之前那张图”“那封邮件”这类问题时必须优先基于这些结构化记忆。",
        "runtime.system.image_read": "如果附件是图片，需要优先使用 image_read(path=...) 读取可见文字和画面内容；不要只报元数据，也不要声称未配置 OCR 或无法看图。",
        "runtime.system.document_read": "如果附件是文档或 .msg，需要优先用 read/search_file/read_section/table_extract 等工具读取内容，不要只根据文件名猜测。",
        "runtime.image_read.intro": "我已经读取了这张图片。",
        "runtime.image_read.visible_text": "识别到的可见文字如下：",
        "runtime.image_read.analysis": "图像说明：{analysis}",
        "runtime.image_read.basic_info": "基础信息：{detail}",
        "runtime.image_read.warning": "注意：{warning}",
        "runtime.attachment_guidance.intro": "附件处理要求：如果 runtime_context_json 里存在 attachments，就把这些本地路径视为当前轮已提供材料。",
        "runtime.attachment_guidance.no_guess": "不要只根据文件名、尺寸或 MIME 猜测内容；需要先调用合适工具再下结论。",
        "runtime.attachment_guidance.image": "图片附件优先使用 image_read(path=...) 获取可见文字和图像内容；不要声称未配置 OCR、无法看图，且不要只返回图片元数据。",
        "runtime.attachment_guidance.image_paths": "本轮图片附件路径示例: {paths}",
        "runtime.attachment_guidance.document": "文档附件优先使用 read、search_file、search_file_multi、read_section、table_extract 或 fact_check_file。",
        "runtime.attachment_guidance.msg": "如果附件是 .msg，正文先用 read，附件再用 mail_extract_attachments。",
        "runtime.act_now.default": "不要只给计划。立即采取下一步实际行动，先调用合适工具或直接执行变更，然后再汇报。",
        "runtime.act_now.image": "本轮存在图片附件。先调用 image_read(path=...) 读取可见文字和画面内容；不要只返回尺寸/格式，也不要说未配置 OCR。",
        "runtime.act_now.image_paths": "优先处理这些图片路径之一: {paths}",
        "runtime.invalid_final_guard.steer": "这不是有效的最终回复：用户已经授权你执行写入/补全任务。不要再请求确认，立即调用合适工具继续。",
        "runtime.invalid_final_guard.blocked": "用户已经授权执行，但模型仍没有调用工具而继续请求确认。本轮已按执行守卫停止。",
        "runtime.cancelled.label": "已取消",
        "runtime.cancelled.text": "已取消当前运行。",
        "runtime.cancelled.detail": "用户已取消当前运行。",
        "runtime.budget.wall_clock": "本轮已达到连续执行时间预算，先在这里停止。",
        "runtime.budget.tool_calls": "本轮已达到工具调用预算，先在这里停止。",
        "runtime.budget.same_tool_repeat": "本轮多次重复同一工具且没有继续推进，先在这里停止。",
        "runtime.budget.no_progress": "本轮多次重复且没有新的有效进展，先在这里停止。",
        "runtime.compaction.mid_turn": "本轮中间上下文已压缩，以支持更长的连续执行。",
        "runtime.empty_response.pending_user_input": "需要你先提供补充输入后我再继续。",
        "runtime.empty_response.default": "(empty response)",
        "chat.auth_missing": "当前还没有可用的模型认证。请在 Settings 里补充当前 provider 的 API key，或切换到一个已经配置好的 provider 后再继续。",
        "chat.backend_start": "后端已接收请求，开始处理。run_id={run_id}, auth_mode={auth_mode}",
        "chat.queue_wait": "当前会话存在并发请求，已排队等待 {queue_wait_ms} ms。",
        "chat.focus_shift": "检测到当前任务焦点切换，本轮会刷新 current_task_focus，但继续保留 thread 记忆。",
        "chat.session_ready": "会话已就绪: {session_id}",
        "chat.replacement_history_compacted": "历史上下文已自动压缩为 replacement history。 generation={generation}, retained={retained_turn_count}",
        "chat.attachments_ready": "附件检查完成: mode={attachment_context_mode}, 请求 {requested_count} 个，命中 {resolved_count} 个。",
        "chat.agent_run_start": "开始通过 vintage_programmer 执行。",
        "chat.agent_run_done": "模型推理结束，开始写入会话与统计。",
        "chat.missing_attachments_warning": "警告: {missing_count} 个附件未找到，可能已被清理或会话刷新，请重新上传。",
        "chat.auto_linked_attachments": "已自动关联历史附件: {attachment_names}",
        "chat.cleared_attachment_context": "已按用户指令清空历史附件关联。",
        "chat.session_saved": "会话已写入本地存储。",
        "chat.token_usage_priced": "费用估算: ${cost_usd:.6f} · input {input_tokens} · output {output_tokens}",
        "chat.token_usage_unpriced": "费用估算未启用: 当前模型 {selected_model} 未匹配价格表。",
        "chat.token_stats_updated": "Token 统计已更新。",
        "chat.overlay_updated": "个体覆层已更新: {overlay_path}",
        "chat.overlay_update_failed": "个体覆层更新失败: {error}",
        "chat.shadow_log_written": "shadow log 已写入: {name}",
        "chat.result_ready": "本轮结果已准备完成。",
    },
    "ja-JP": {
        "error.request_failed": "リクエストに失敗しました。しばらくしてから再試行してください。",
        "error.rate_limit": "モデル提供元がレート制限中です。しばらくしてから再試行してください。",
        "error.auth": "認証に失敗しました。OpenRouter / OpenAI-compatible のキーを確認してください。",
        "error.upstream": "モデル提供元が一時的に利用できません。しばらくしてから再試行してください。",
        "error.request_failed_detail": "リクエストに失敗しました。しばらくしてから再試行するか、詳細を確認してください。",
        "health.permission_summary.full_filesystem": "フルファイルシステムアクセスが有効です",
        "health.permission_summary.allowed_roots": "許可ルート {count} 件: {root_names}",
        "runtime.style.short": "回答はできるだけ短く。まず結論を述べ、その後は重要点を最大 3 つまで示す。",
        "runtime.style.normal": "回答は明確で実行可能にし、冗長さを避ける。",
        "runtime.style.long": "必要に応じて詳しく書いてよいが、構造化を保ち、次の行動を優先して示す。",
        "runtime.system.language_instruction": "既定では簡潔で自然な日本語で回答する。ユーザーが別の言語を明示した場合や翻訳を求めた場合のみ切り替える。",
        "runtime.system.output_requirements": "出力要件: 思考連鎖は出さない。事実を捏造しない。不確かな点は明示する。ツールを使った場合は必ずその結果に基づいて結論を書く。",
        "runtime.system.inline_message_analysis": "ユーザーがメッセージ内にコード、XML、HTML、JSON、YAML、または長文を直接貼った場合は、その内容をまずその場で分析し、既定で workspace パスを聞き返さないこと。",
        "runtime.system.inline_error_analysis": "エラー、コード片、設定テキスト、ログが貼られた場合は、それを今回分析すべき対象として扱う。リポジトリのファイル、ディレクトリ、Web ページ、またはコマンド実行を明示的に求められたときのみ、先にツールを使うこと。",
        "runtime.system.attachment_context": "runtime_context_json に attachments の name/path があれば、それをこの turn で既に渡されたコンテキストとして扱い、添付を否定したり再度パス説明を求めたりしないこと。",
        "runtime.system.focus_context": "runtime_context_json.current_task_focus に goal/cwd/active_files/active_attachments がある場合は、それを現在タスクのハードコンテキストとして引き継ぎ、ディレクトリ・ファイル・添付が分からないと繰り返さないこと。",
        "runtime.system.thread_memory": "runtime_context_json.thread_memory.recent_tasks または recalled_context に直近タスクや添付の想起結果がある場合は、「さっき何を頼んだ？」「前の画像は？」「あのメールは？」のような質問に、必ずその構造化メモリを優先して答えること。",
        "runtime.system.image_read": "添付が画像の場合は、まず image_read(path=...) を使って可視テキストと画像内容を読むこと。メタデータだけを返したり、OCR 未設定や画像が読めないと主張したりしないこと。",
        "runtime.system.document_read": "添付が文書や .msg の場合は、まず read/search_file/read_section/table_extract などのツールで内容を読むこと。ファイル名だけで推測しないこと。",
        "runtime.image_read.intro": "この画像は読み取り済みです。",
        "runtime.image_read.visible_text": "認識できた可視テキストは次のとおりです。",
        "runtime.image_read.analysis": "画像の要約: {analysis}",
        "runtime.image_read.basic_info": "基本情報: {detail}",
        "runtime.image_read.warning": "注意: {warning}",
        "runtime.attachment_guidance.intro": "添付の扱い: runtime_context_json に attachments があれば、それらのローカルパスをこの turn で既に渡された資料として扱ってください。",
        "runtime.attachment_guidance.no_guess": "ファイル名、サイズ、MIME だけで内容を推測せず、適切なツールを先に呼んでから結論を出してください。",
        "runtime.attachment_guidance.image": "画像添付はまず image_read(path=...) を使って可視テキストと画像内容を取得してください。OCR 未設定や画像が読めないとは言わず、メタデータだけも返さないでください。",
        "runtime.attachment_guidance.image_paths": "今回の画像添付パス例: {paths}",
        "runtime.attachment_guidance.document": "文書添付はまず read、search_file、search_file_multi、read_section、table_extract、fact_check_file を使って内容を読んでください。",
        "runtime.attachment_guidance.msg": ".msg 添付は本文を read で、添付を mail_extract_attachments で処理してください。",
        "runtime.act_now.default": "計画だけで終わらせず、次の実作業にすぐ着手してください。適切なツール呼び出しか直接の変更を先に行い、その後で報告してください。",
        "runtime.act_now.image": "この turn には画像添付があります。まず image_read(path=...) を呼んで可視テキストと画面内容を読んでください。サイズや形式だけを返したり、OCR 未設定と言ったりしないでください。",
        "runtime.act_now.image_paths": "優先して扱う画像パス候補: {paths}",
        "runtime.invalid_final_guard.steer": "これは有効な最終回答ではありません。ユーザーは書き込み/補完作業をすでに許可しています。確認を繰り返さず、適切なツールをすぐ呼び出して続行してください。",
        "runtime.invalid_final_guard.blocked": "ユーザーは実行を許可済みですが、モデルがツールを呼ばず確認を繰り返したため、この turn は実行ガードにより停止しました。",
        "runtime.cancelled.label": "キャンセル済み",
        "runtime.cancelled.text": "現在の実行はキャンセルされました。",
        "runtime.cancelled.detail": "ユーザーが現在の実行をキャンセルしました。",
        "runtime.budget.wall_clock": "この turn は連続実行時間の予算に達したため、ここで停止します。",
        "runtime.budget.tool_calls": "この turn はツール呼び出し予算に達したため、ここで停止します。",
        "runtime.budget.same_tool_repeat": "同じツールの繰り返しが続き、進展がなかったため、この turn はここで停止します。",
        "runtime.budget.no_progress": "同様の処理が繰り返され、新しい有効な進展がなかったため、この turn はここで停止します。",
        "runtime.compaction.mid_turn": "長い連続実行を続けるため、この turn の中間コンテキストを圧縮しました。",
        "runtime.empty_response.pending_user_input": "補足入力をもらえれば続行できます。",
        "runtime.empty_response.default": "(empty response)",
        "chat.auth_missing": "現在利用可能なモデル認証がありません。Settings で現在の provider の API key を設定するか、既に設定済みの provider に切り替えてから続行してください。",
        "chat.backend_start": "バックエンドがリクエストを受信しました。処理を開始します。run_id={run_id}, auth_mode={auth_mode}",
        "chat.queue_wait": "このセッションには並行リクエストがあり、{queue_wait_ms} ms 待機しました。",
        "chat.focus_shift": "現在の作業フォーカスの切り替えを検知しました。この turn では current_task_focus を更新しますが、thread メモリは保持します。",
        "chat.session_ready": "セッションの準備ができました: {session_id}",
        "chat.replacement_history_compacted": "履歴コンテキストを replacement history として自動圧縮しました。 generation={generation}, retained={retained_turn_count}",
        "chat.attachments_ready": "添付チェック完了: mode={attachment_context_mode}, 要求 {requested_count} 件, 解決 {resolved_count} 件。",
        "chat.agent_run_start": "vintage_programmer による実行を開始します。",
        "chat.agent_run_done": "モデル推論が完了しました。セッションと統計の書き込みを開始します。",
        "chat.missing_attachments_warning": "警告: {missing_count} 件の添付が見つかりませんでした。削除されたかセッション更新で失われた可能性があります。再アップロードしてください。",
        "chat.auto_linked_attachments": "過去の添付を自動関連付けしました: {attachment_names}",
        "chat.cleared_attachment_context": "ユーザー指示により過去の添付関連付けをクリアしました。",
        "chat.session_saved": "セッションをローカルストレージへ保存しました。",
        "chat.token_usage_priced": "コスト見積もり: ${cost_usd:.6f} · input {input_tokens} · output {output_tokens}",
        "chat.token_usage_unpriced": "コスト見積もりは無効です: 現在のモデル {selected_model} は価格表に一致しません。",
        "chat.token_stats_updated": "Token 統計を更新しました。",
        "chat.overlay_updated": "個別オーバーレイを更新しました: {overlay_path}",
        "chat.overlay_update_failed": "個別オーバーレイの更新に失敗しました: {error}",
        "chat.shadow_log_written": "shadow log を出力しました: {name}",
        "chat.result_ready": "この turn の結果を準備しました。",
    },
    "en": {
        "error.request_failed": "Request failed. Please try again shortly.",
        "error.rate_limit": "The model provider is rate-limiting requests. Please try again shortly.",
        "error.auth": "Authentication failed. Check the OpenRouter / OpenAI-compatible key.",
        "error.upstream": "The model provider is temporarily unavailable. Please try again shortly.",
        "error.request_failed_detail": "Request failed. Please try again or inspect the error details.",
        "health.permission_summary.full_filesystem": "full filesystem access enabled",
        "health.permission_summary.allowed_roots": "{count} allowed roots: {root_names}",
        "runtime.style.short": "Keep the answer brief. Lead with the conclusion, then give at most 3 key points.",
        "runtime.style.normal": "Keep the answer clear and actionable. Avoid unnecessary length.",
        "runtime.style.long": "The answer may be more detailed, but keep it structured and action-oriented.",
        "runtime.system.language_instruction": "By default, answer in concise natural English. Switch only if the user explicitly uses another language or requests translation.",
        "runtime.system.output_requirements": "Output requirements: do not reveal chain-of-thought; do not invent facts; state uncertainty clearly; if tools were used, ground conclusions in tool results.",
        "runtime.system.inline_message_analysis": "When the user pastes code, XML, HTML, JSON, YAML, or long text directly into the message, analyze that content in place first instead of defaulting to a workspace path follow-up.",
        "runtime.system.inline_error_analysis": "When the user pastes an error, code snippet, config text, or logs, treat that content as the primary object to analyze for this turn. Only prioritize tools first if the user explicitly asks to inspect repo files, directories, web pages, or run commands.",
        "runtime.system.attachment_context": "If runtime_context_json already provides attachment names or paths, treat them as current-turn context. Do not deny the attachment or ask the user to restate the path first.",
        "runtime.system.focus_context": "If runtime_context_json.current_task_focus already provides goal/cwd/active_files/active_attachments, treat them as hard context for the current task. Do not claim you do not know the directory, file, or attachment.",
        "runtime.system.thread_memory": "If runtime_context_json.thread_memory.recent_tasks or recalled_context already includes recent task or attachment recall, answer questions like 'what did I just ask you to do', 'that previous image', or 'that email' from that structured memory first.",
        "runtime.system.image_read": "If an attachment is an image, use image_read(path=...) first to read visible text and image content. Do not only report metadata, and do not claim OCR is unavailable or that you cannot view the image.",
        "runtime.system.document_read": "If an attachment is a document or .msg file, use read/search_file/read_section/table_extract to inspect its contents first. Do not guess from the filename alone.",
        "runtime.image_read.intro": "I have already read the image.",
        "runtime.image_read.visible_text": "The visible text I detected is:",
        "runtime.image_read.analysis": "Image summary: {analysis}",
        "runtime.image_read.basic_info": "Basic info: {detail}",
        "runtime.image_read.warning": "Note: {warning}",
        "runtime.attachment_guidance.intro": "Attachment handling: if runtime_context_json includes attachments, treat those local paths as material already provided for this turn.",
        "runtime.attachment_guidance.no_guess": "Do not infer content from the filename, size, or MIME type alone. Call the appropriate tool before drawing conclusions.",
        "runtime.attachment_guidance.image": "For image attachments, use image_read(path=...) first to get visible text and image content. Do not claim OCR is unavailable or that you cannot read the image, and do not return metadata only.",
        "runtime.attachment_guidance.image_paths": "Example image attachment paths for this turn: {paths}",
        "runtime.attachment_guidance.document": "For document attachments, prefer read, search_file, search_file_multi, read_section, table_extract, or fact_check_file first.",
        "runtime.attachment_guidance.msg": "If the attachment is a .msg file, read the body with read and extract attachments with mail_extract_attachments.",
        "runtime.act_now.default": "Do not stop at a plan. Take the next concrete action now by calling the appropriate tool or applying the change directly, then report back.",
        "runtime.act_now.image": "This turn includes image attachments. Call image_read(path=...) first to read visible text and screen contents. Do not only return size/format or claim OCR is unavailable.",
        "runtime.act_now.image_paths": "Prioritize one of these image paths: {paths}",
        "runtime.invalid_final_guard.steer": "This is not a valid final answer: the user already authorized the write/completion task. Do not ask for confirmation again; call the appropriate tool now.",
        "runtime.invalid_final_guard.blocked": "The user authorized execution, but the model continued asking for confirmation without calling tools. This turn stopped under the execution guard.",
        "runtime.cancelled.label": "Cancelled",
        "runtime.cancelled.text": "The current run was cancelled.",
        "runtime.cancelled.detail": "The user cancelled the current run.",
        "runtime.budget.wall_clock": "This turn reached the continuous execution time budget, so it is stopping here.",
        "runtime.budget.tool_calls": "This turn reached the tool-call budget, so it is stopping here.",
        "runtime.budget.same_tool_repeat": "The same tool repeated too many times without progress, so this turn is stopping here.",
        "runtime.budget.no_progress": "This turn repeated without new progress, so it is stopping here.",
        "runtime.compaction.mid_turn": "The mid-turn context was compacted to support longer continuous execution.",
        "runtime.empty_response.pending_user_input": "I need additional input from you before I can continue.",
        "runtime.empty_response.default": "(empty response)",
        "chat.auth_missing": "No usable model authentication is available yet. Add the current provider API key in Settings, or switch to a provider that is already configured.",
        "chat.backend_start": "The backend has accepted the request and started processing. run_id={run_id}, auth_mode={auth_mode}",
        "chat.queue_wait": "This session had a concurrent request and waited in queue for {queue_wait_ms} ms.",
        "chat.focus_shift": "A task focus shift was detected. This turn will refresh current_task_focus while keeping thread memory.",
        "chat.session_ready": "Session is ready: {session_id}",
        "chat.replacement_history_compacted": "Historical context was auto-compacted into replacement history. generation={generation}, retained={retained_turn_count}",
        "chat.attachments_ready": "Attachment check completed: mode={attachment_context_mode}, requested {requested_count}, resolved {resolved_count}.",
        "chat.agent_run_start": "Starting execution through vintage_programmer.",
        "chat.agent_run_done": "Model inference finished. Writing session state and statistics next.",
        "chat.missing_attachments_warning": "Warning: {missing_count} attachments were not found. They may have been cleaned up or lost after a session refresh. Please upload them again.",
        "chat.auto_linked_attachments": "Auto-linked historical attachments: {attachment_names}",
        "chat.cleared_attachment_context": "Historical attachment links were cleared based on the user instruction.",
        "chat.session_saved": "The session has been written to local storage.",
        "chat.token_usage_priced": "Estimated cost: ${cost_usd:.6f} · input {input_tokens} · output {output_tokens}",
        "chat.token_usage_unpriced": "Cost estimation is disabled: the current model {selected_model} does not match the pricing table.",
        "chat.token_stats_updated": "Token statistics have been updated.",
        "chat.overlay_updated": "Per-agent overlay updated: {overlay_path}",
        "chat.overlay_update_failed": "Per-agent overlay update failed: {error}",
        "chat.shadow_log_written": "shadow log written: {name}",
        "chat.result_ready": "The turn result is ready.",
    },
}


def supported_locales() -> list[str]:
    return list(SUPPORTED_LOCALES)


def normalize_locale(
    raw: str | None,
    fallback: str = "ja-JP",
    supported: tuple[str, ...] | list[str] | None = None,
) -> str:
    allowed = tuple(supported or SUPPORTED_LOCALES)
    fallback_normalized = _LOCALE_ALIASES.get(str(fallback or "").strip().lower(), str(fallback or "").strip() or "ja-JP")
    if fallback_normalized not in allowed:
        fallback_normalized = allowed[0] if allowed else "ja-JP"

    value = str(raw or "").strip()
    if not value:
        return fallback_normalized

    lowered = value.lower()
    if value in allowed:
        return value
    if lowered in _LOCALE_ALIASES:
        alias = _LOCALE_ALIASES[lowered]
        if alias in allowed:
            return alias
    for candidate in allowed:
        if lowered == candidate.lower():
            return candidate
        if lowered.startswith(candidate.lower().split("-", 1)[0]):
            return candidate
    return fallback_normalized


def _lookup(locale: str, key: str) -> str:
    normalized = normalize_locale(locale)
    search_order = [normalized]
    if normalized != "en":
        search_order.append("en")
    if normalized != "zh-CN":
        search_order.append("zh-CN")
    for candidate in search_order:
        bundle = _TRANSLATIONS.get(candidate) or {}
        if key in bundle:
            return bundle[key]
    return key


def translate(locale: str, key: str, **values: Any) -> str:
    template = _lookup(locale, key)
    if not values:
        return template
    try:
        return template.format(**values)
    except Exception:
        return template


def response_style_hint(locale: str, style: str) -> str:
    normalized_style = str(style or "normal").strip().lower() or "normal"
    if normalized_style not in {"short", "normal", "long"}:
        normalized_style = "normal"
    return translate(locale, f"runtime.style.{normalized_style}")
