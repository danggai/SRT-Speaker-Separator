# SRT Speaker Editor

대사마다 화자를 지정해 화자별 SRT로 나누는 Windows용 자막 편집기입니다.

## 주요 기능

- 자막 표와 파형 타임라인에서 텍스트·시간·화자 편집
- Whisper로 음성/영상에서 자막 자동 생성
- pyannote로 화자 자동 분석
- 화자별 `.srt` 내보내기

## 사용 방법

1. SRT 또는 음성/영상 파일을 끌어다 놓거나 `열기`로 엽니다.
2. 화자를 지정합니다. 숫자 키 `1`~`9`로 바로 지정할 수 있습니다.
3. `저장`(`Ctrl+S`) 후 `내보내기`로 화자별 SRT를 만듭니다.

## 참고

- 화자 분석에는 HuggingFace 토큰이 필요합니다. [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)에서 약관에 동의한 뒤 설정 창에 입력하세요.
- NVIDIA GPU 사용을 권장합니다.
