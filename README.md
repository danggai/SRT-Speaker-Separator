# SRT 화자 분리기 (srt_speaker_separator)

SRT 자막을 `[화자] 내용` 형식으로 구분하여
화자별 `.srt` 파일로 분리하는 간단한 도구입니다.

---

## 📌 주요 기능

* `[화자] 내용` 형식 기반 자동 분리
* 화자별 `.srt` 파일 생성 (예: `a.srt`, `b.srt`)
* 태그 없는 자막은 별도 파일로 저장 (`*_untagged.srt`)
* 간단한 자막 편집 기능

---

## ▶ 사용 방법

* exe 실행 후 SRT 파일 드래그 & 드롭
  또는:

```bash
srt_speaker_separator.exe input.srt
```

---

## 🧩 예시

입력:

```srt
1
00:00:01,000 --> 00:00:03,000
[a] 안녕하세요

2
00:00:04,000 --> 00:00:06,000
[b] 반갑습니다
```

---

## 📤 출력

* `a.srt`
* `b.srt`
* `input_untagged.srt` (태그 없는 자막이 있을 경우만 생성)

---

## 🛠 빌드 방법

```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name srt_speaker_separator srt_speaker_separator.py
```

결과:

```
dist/srt_speaker_separator.exe
```

---

## 📁 코드 구조

```
srt_speaker_separator.py   실행 진입점 (필수 패키지 확인 후 앱 실행, 빌드 대상)
srt_editor/
  app.py        메인 창(SRTEditor)과 main()
  config.py     설정 파일 로드/저장
  theme.py      색상·폰트
  srt_io.py     SRT 파싱/저장, 화자 태그 패턴
  speech.py     음성 인식·화자 분리 로직 (GUI 없음)
  media.py      미디어 재생
  widgets.py    공용 위젯
  version.py    버전 정보
  ui/           SRTEditor 기능별 믹스인
    transcribe.py  자막 자동 생성, 고유명사 사전
    diarize.py     화자 분석
    settings.py    설정 창
    timeline.py    재생바·파형
    table.py       자막 표
    speakers.py    화자 사이드바·색상
    editing.py     편집·실행 취소
    playback.py    재생·키보드 이동
    files.py       열기/저장/내보내기
tools/
  eval_accuracy.py  자막/화자 분리 정확도 평가
```

---

끝.
