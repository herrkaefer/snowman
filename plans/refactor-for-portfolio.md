# Snowman Refactor Plan — Portfolio-Ready Voice Assistant

> 目标：将 Snowman 打造成求职 portfolio 项目，展示 Voice AI / AI Engineer 能力
> 预计耗时：3-4 天
> 创建日期：2026-03-05

---

## 现状分析

- `simple_local_assistant.py` 1454 行单文件，所有逻辑耦合在一起
- LLM 响应非 streaming（`stream=False`），延迟 = STT + LLM + TTS 串行累加
- `ENABLE_INTERRUPTION = False`，中断功能代码存在但未启用
- `cobra_vad.py` 有 150+ 行注释掉的遗留代码
- 全部使用 `print` 输出，无 logging 框架
- README 可用但缺少架构图和性能指标

---

## Phase 1: 代码重构（1.5 天）

### 目标

将单文件拆成模块化结构，主文件从 1454 行降到 ~150 行。

### 目标结构

```
snowman/
├── main.py                    # 入口，~50 行
├── assistant.py               # VoiceAssistant 类，~150 行（组装+主循环）
├── config.py                  # Settings dataclass + constants，从 .env 加载
├── audio/
│   ├── __init__.py
│   ├── recorder.py            # PvRecorder 封装
│   ├── playback.py            # 跨平台音频播放（提取 play_sound_effect 的 80 行 if/elif）
│   └── vad.py                 # 现有 cobra_vad.py 清理（删掉 150 行注释代码）
├── speech/
│   ├── __init__.py
│   ├── recognizer.py          # faster-whisper 封装（transcribe_audio）
│   ├── synthesizer.py         # Edge TTS 封装（speak_text_edge）
│   └── wake_word.py           # Porcupine 封装
├── ai/
│   ├── __init__.py
│   ├── llm.py                 # Gemini 封装（get_ai_response）
│   ├── search.py              # Tavily 封装（perform_search）
│   └── prompts.py             # 现有 prompts.py
└── conversation/
    ├── __init__.py
    ├── manager.py             # handle_conversation 逻辑
    └── metrics.py             # 统计和报告
```

### 步骤

#### 1.1 创建 `config.py`

- 把 `simple_local_assistant.py` 里散落的常量（L42-114）集中到 `Settings` dataclass
- 包含：SAMPLE_RATE, SILENCE_THRESHOLD, 音效路径映射, 语言配置, 超时设置等
- 从 `.env` 读取 API keys、设备配置、模型大小等
- 加 type hints 和 validation

#### 1.2 提取 `audio/` 模块

**`audio/recorder.py`** — PvRecorder 封装
- 从 `__init__` 里提取 PvRecorder 初始化
- 提供 `start()`, `stop()`, `read()` 接口

**`audio/playback.py`** — 跨平台音频播放
- 提取 `play_sound_effect()` (L540-631) 的 80 行平台判断逻辑
- 提取 `speak_text_edge()` 里的播放部分 (L1100-1181)
- 抽象为 `AudioPlayer` 类，封装 platform-specific 逻辑

**`audio/vad.py`** — 从 `cobra_vad.py` 清理
- 删除 150+ 行注释掉的 `record_audio` 遗留代码
- 重命名类为 `VoiceActivityDetector`
- 加 type hints

#### 1.3 提取 `speech/` 模块

**`speech/recognizer.py`** — faster-whisper 封装
- 提取 `init_speech_recognition()` (L249-289) 和 `transcribe_audio()` (L720-797)
- 返回 `TranscriptionResult(text, language, confidence)` dataclass

**`speech/synthesizer.py`** — Edge TTS 封装
- 提取 `init_edge_tts()` (L291-327) 和 `speak_text_edge()` (L1038-1181)
- 分离 TTS 生成和音频播放（为 Phase 2 streaming 做准备）

**`speech/wake_word.py`** — Porcupine 封装
- 提取 `init_porcupine()` (L329-402) 和 `listen_for_wake_word()` (L633-681)

#### 1.4 提取 `ai/` 模块

**`ai/llm.py`** — Gemini 封装
- 提取 `init_gemini()` (L419-468) 和 `get_ai_response()` (L894-1014)
- 分离 JSON 解析逻辑
- 预留 streaming 接口

**`ai/search.py`** — Tavily 封装
- 提取 `init_search_apis()` (L470-505) 和 `perform_search()` (L799-892)

**`ai/prompts.py`** — 直接移入现有 `prompts.py`

#### 1.5 提取 `conversation/` 模块

**`conversation/manager.py`** — 对话管理
- 提取 `handle_conversation()` (L1220-1363)
- 管理对话状态：录音 → 转录 → LLM → 播放 → 循环

**`conversation/metrics.py`** — 统计报告
- 提取 `calculate_session_stats()` 和 `print_session_stats()` (L1201-1398)
- `ConversationContext` dataclass 保存 session 状态

#### 1.6 重写 `assistant.py`

- 组装所有组件，~150 行
- `VoiceAssistant.__init__()` 创建各模块实例
- `run()` 方法：主循环 wake word → conversation → cleanup

#### 1.7 全局改进

- 用 Python `logging` 替换所有 `print`
- 加 type hints（80%+ 覆盖率）
- 保留 `simple_local_assistant.py` 作为 legacy 入口（import 新模块）

---

## Phase 2: Streaming 响应（1 天）

### 目标

LLM 边出 token 边送 TTS，体感延迟从串行累加变为近实时。

### 关键问题

当前 LLM 返回 JSON 格式（`{need_search, response_text, reason}`），与 streaming 冲突。

**解决方案：两阶段调用**
1. 第一次调用（非 streaming）：让 LLM 判断是否需要搜索，返回 JSON
2. 如需搜索 → 执行搜索 → 带搜索结果再次调用
3. 最终回答改用 streaming 输出纯文本（修改 prompt，不要求 JSON 格式）

### 步骤

#### 2.1 `ai/llm.py` — 添加 streaming 方法

```python
def send_message_stream(self, prompt: str) -> Generator[str, None, None]:
    """Stream LLM response, yield complete sentences."""
    response = self.chat.send_message(prompt, stream=True)
    buffer = ""
    for chunk in response:
        buffer += chunk.text
        # 按句号/问号/感叹号/换行分割
        while has_complete_sentence(buffer):
            sentence, buffer = split_first_sentence(buffer)
            yield sentence
    if buffer.strip():
        yield buffer.strip()
```

#### 2.2 `speech/synthesizer.py` — 逐句合成+播放

```python
async def speak_streaming(self, sentence_generator: Generator[str, None, None]):
    """Synthesize and play each sentence as it arrives."""
    for sentence in sentence_generator:
        audio_path = await self._synthesize_to_file(sentence)
        self._play_audio(audio_path)
```

#### 2.3 `conversation/manager.py` — 串联 streaming pipeline

- 搜索判断阶段：非 streaming，快速获取 JSON
- 回答阶段：streaming，逐句 TTS 播放
- 更新 metrics 收集逻辑

#### 2.4 `ai/prompts.py` — 添加 streaming 专用 prompt

- 新增 `STREAMING_SYSTEM_PROMPT`：不要求 JSON，直接输出自然语言
- 保留原有 `SYSTEM_PROMPT` 用于搜索判断阶段

---

## Phase 3: README + 架构文档（0.5 天）

### 目标

面试官 30 秒内理解项目价值。

### README.md 重写内容

#### 3.1 标题区

- 项目名 + 一句话描述："A privacy-focused local voice assistant for Raspberry Pi"
- Badge: Python 3.8+ | License | Platform

#### 3.2 架构图（Mermaid）

```
Mic → [Porcupine Wake Word] → [Cobra VAD + Recording]
                                        ↓
                                [Whisper STT (local)]
                                        ↓
                              [Gemini 2.0 Flash (cloud)]
                                   ↓          ↓
                            [Tavily Search]   [Streaming Response]
                                                ↓
                                        [Edge TTS → Speaker]
```

#### 3.3 性能指标表

从现有 metrics 系统跑一轮真实对话，采集数据：

| Component | Avg Latency | Runs On |
|-----------|------------|---------|
| Wake Word Detection | <50ms | Local (Porcupine) |
| Voice Activity Detection | Real-time | Local (Cobra VAD) |
| Speech-to-Text | ~500ms | Local (Whisper base) |
| LLM Response | ~800ms | Cloud (Gemini 2.0 Flash) |
| Text-to-Speech | ~300ms | Local (Edge TTS) |
| **Total (non-streaming)** | **~1.6s** | |
| **Total (streaming)** | **~0.8s first audio** | |

#### 3.4 Features 列表

- Local-first：STT/TTS/VAD 全部本地运行
- Streaming responses：边生成边播放，低延迟体验
- Multi-language：English + Chinese 自动检测切换
- Raspberry Pi deployment：systemd 服务，开机自启
- Web search integration：可选 Tavily 搜索增强
- Modular architecture：可独立替换任何组件

#### 3.5 Quick Start（3 步）

```bash
cp .env.example .env  # 填入 API keys
pip install -r requirements.txt
python main.py
```

#### 3.6 项目结构说明

展示模块化设计，每个目录一句话解释。

#### 3.7 Configuration Reference

所有 .env 变量分组说明。

---

## Phase 4（可选）: Interruption 打通（0.5 天）

### 目标

用户说话时打断助手播放，展示对实时对话系统的理解。

### 步骤

#### 4.1 修改 `speech/synthesizer.py`

- 播放时不再完全暂停 VAD
- 播放改为可中断模式：用 subprocess 播放，保存 PID

#### 4.2 新增中断检测逻辑

- TTS 播放期间，VAD 持续监听
- 检测到语音概率 > `INTERRUPTION_THRESHOLD` (0.1) → 停止播放
- Kill 播放进程，清空音频队列

#### 4.3 修改 `conversation/manager.py`

- `speak_with_interruption()` 方法
- 中断后回到录音状态，处理新输入
- 加 `INTERRUPTION_ENABLED` 环境变量控制开关

### 面试话术价值

> "实现了 barge-in 中断——用户可以随时打断助手说话。这在生产级语音系统（如 Alexa、Google Assistant）中是标准功能，但实现起来有挑战：需要在播放音频的同时持续监听麦克风，区分回声和真实用户语音。"

---

## 执行时间表

| 天数 | 任务 | 产出 | 验证方式 |
|------|------|------|----------|
| Day 1 | Phase 1 前半：config + audio + speech 提取 | 主文件从 1454→~800 行 | 跑通完整对话 |
| Day 2 | Phase 1 后半：ai + conversation 提取，重写 assistant.py | 主文件 ~150 行 | 跑通完整对话 |
| Day 3 | Phase 2：Streaming 响应 | 首字节延迟降低 50%+ | 对比 streaming vs non-streaming 延迟 |
| Day 4 | Phase 3：README + 文档；Phase 4（可选）：Interruption | 面试可展示状态 | README 阅读体验 |

## 注意事项

- 每个 Phase 结束后在树莓派上测试一轮，确保没有 regression
- 重构过程保持 git 提交粒度小，每完成一个模块提交一次
- 保留 `simple_local_assistant.py` 备份，确保随时可回退
- streaming 实现注意 Edge TTS 的 async 特性，避免 event loop 冲突
