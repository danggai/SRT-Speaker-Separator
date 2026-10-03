# SRT Speaker Editor

영상·음성의 자막을 만들고, 대사마다 화자를 지정해 화자별 SRT로 나누는 Windows용 자막 편집기입니다.
여러 사람이 대화하는 방송 클립 편집을 염두에 두고 만들었습니다.

## 주요 기능

- **자막 편집**: 자막 표와 파형 타임라인에서 텍스트·시간·화자를 편집. 실행 취소, 자막 분할, 레이어 지원
- **자막 자동 생성**: 음성/영상 파일에서 Whisper(whisperx)로 자막 생성. 한국어 고정, 고유명사 사전 지원
- **화자 분석**: pyannote로 화자를 분리해 자막에 화자를 자동 지정
- **화자별 내보내기**: 화자마다 `.srt` 파일로 저장. 화자가 없는 자막은 `*_untagged.srt`
- 화자 정보는 SRT 안에 `[화자] 내용` 형식으로 저장되어 다시 열면 그대로 복원됩니다.

## 사용 방법

1. SRT 또는 음성/영상 파일을 창에 끌어다 놓거나 `파일 열기`로 엽니다.
   - SRT: 같은 이름의 음성/영상이 있으면 함께 열립니다.
   - 음성/영상만: 같은 이름의 SRT가 있으면 열고, 없으면 자막 자동 생성을 묻습니다.
2. 자막 표나 타임라인에서 화자를 지정·수정합니다. 숫자 키 `1`~`9`로 화자를 바로 지정할 수 있습니다.
3. `저장`(`Ctrl+S`)으로 화자 태그가 붙은 SRT를 저장하고, `내보내기`로 화자별 SRT를 만듭니다.

## 자동 자막 · 화자 분석 준비

- 처음 사용할 때 필요한 패키지(whisperx 등)를 자동으로 설치합니다.
- 화자 분석에는 HuggingFace 토큰이 필요합니다. [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 페이지에서 이용 약관에 동의한 뒤 토큰을 설정 창에 입력하세요.
- NVIDIA GPU 사용을 권장합니다. CPU에서도 동작하지만 느리며, 이때는 인식 모드 `균형`을 권장합니다.

## 개발

```bash
pip install -r requirements.txt
python srt_speaker_separator.py
```

빌드(PyInstaller):

```bash
python -m PyInstaller --onefile --windowed --name SRTSpeakerEditor srt_speaker_separator.py
```

코드 구조:

```
srt_speaker_separator.py   진입점 (필수 패키지 확인 후 실행, 빌드 대상)
srt_editor/
  app.py                   메인 창
  speech.py                음성 인식·화자 분리 로직 (GUI 없음)
  srt_io.py, config.py, theme.py, media.py, widgets.py, ime.py, version.py
  ui/                      기능별 화면 코드 (자동 자막, 화자 분석, 타임라인, 자막 표 등)
tools/eval_accuracy.py     정답 SRT 대비 자막·화자 분리 정확도 평가
```
