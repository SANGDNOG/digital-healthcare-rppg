# 기여 안내

연구용 로컬 rPPG MVP다. 실제 생체 정확도·스트레스 분류 성능은 아직 검증하지 않았다. [팀 현황과 우선순위](docs/TEAM_STATUS.md), [사용법과 데이터 계약](docs/USAGE.md), [데이터 접근 조건](docs/DATA_ACCESS.md)을 먼저 읽는다.

## 설치와 첫 실행

Python 3.11과 uv를 사용한다. 저장소를 clone한 뒤 루트에서 실행한다. 아래는 uv가 PATH에 설치된 경우이며, 별도 tooling 환경을 쓰면 `uv`를 `.tools/bin/uv`로 대체한다. 환경과 데이터는 장비마다 따로 준비한다.

```bash
bash scripts/setup.sh
uv run --locked python scripts/doctor.py
uv run --locked pytest -q
uv run --locked python -m rppg --help

# 실행할 때마다 새 이름을 만들어 기존 결과와 분리한다.
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
uv run --locked python -m rppg demo --output "runs/demo-$RUN_ID"
uv run --locked python -m rppg analyze \
  --rgb "runs/demo-$RUN_ID/rgb.csv" --output "runs/rgb-$RUN_ID"
```

setup은 잠금 의존성 설치와 기본 디렉터리 준비를 수행하며 데이터 다운로드·학습은 하지 않는다. 첫 설치에는 패키지/관리 Python 다운로드가 필요할 수 있다. doctor의 `cpu_ready`는 환경 준비 상태다. 알려진 자동 테스트 기준은 98개이며 PR에는 직접 실행한 실제 결과를 적는다. demo는 수학적 합성 입력으로 실제 영상 성능을 입증하지 않는다.

출력 디렉터리가 이미 있으면 CLI가 실패한다. 실패한 실행도 일부 폴더를 남길 수 있으므로 원인을 확인하고 `RUN_ID`를 새로 만든다. 기존 결과 삭제나 덮어쓰기를 재실행 절차로 삼지 않는다.

## 실제 입력은 조건 확인 후

직접 이용 권한·동의를 확인한 파일을 아래 예시 위치에 준비한 경우만 실행한다. 샘플은 저장소에 포함되지 않는다.

```bash
uv run --locked python -m rppg analyze \
  --video data/raw/consented/sample.mp4 --max-seconds 120 \
  --output "runs/video-$RUN_ID"
```

평가는 별도 단계다. 아래는 동기화를 입증하고 중복 없는 `timestamp_s,hr_bpm` reference를 만든 **뒤에만** 실행할 예시다. CLI는 raw BVP 변환·자동 정렬·시간 shift 탐색을 하지 않는다. UBFC-rPPG subject1의 중복 reference 시각을 임의로 제거해 정확도 검증 완료로 표현하지 않는다.

```bash
uv run --locked python -m rppg evaluate \
  --predictions "runs/video-$RUN_ID/windows.csv" \
  --reference data/processed/aligned-reference.csv --tolerance 0.5 \
  --output "runs/evaluation-$RUN_ID"
```

카메라 점검은 필수 온보딩 단계가 아니다. 사용자가 촬영 환경·권한을 확인하고 캡처를 명시적으로 선택한 경우에만 다음 명령을 직접 실행한다. GUI·원본 영상 녹화 없이 RGB 평균을 저장하며 실제 장치 동작은 별도 검증 대상이다.

```bash
uv run --locked python -m rppg capture --camera 0 --duration 60 \
  --output "runs/capture-$RUN_ID"
```

## Issue → 브랜치 → PR

1. Issue에 목적, 소유 파일, 의존성, 수락 기준을 적고 작업 담당을 합의한다. [백로그](docs/TEAM_STATUS.md)의 역할은 아직 배정되지 않았다. 예전 일정은 재확인 전 현재 마감으로 쓰지 않는다.
2. 기본 브랜치를 최신화하고 `git switch -c feat/roi-stability`처럼 작업 브랜치를 만든다. 쓰기 권한이 없으면 공개 저장소를 fork하고 fork의 브랜치에서 작업한 뒤 원본 저장소 기본 브랜치로 PR을 연다. 원본 갱신은 `upstream` remote로 가져온다. 공개 fork에도 동일한 데이터 제외 규칙을 적용한다.
3. 합의한 파일만 수정한다. 겹치는 파일은 다른 기여자와 순서를 조정하고 기존 변경을 되돌리지 않는다. 의존성 변경이 필요하면 이유와 lock 갱신을 함께 검토한다.
4. 관련 테스트와 전체 `uv run --locked pytest -q`를 실행한다. 동작 변경은 경계·실패 경로 회귀 검증을 포함한다. 문서만 바꾸면 명령·링크·계약의 일치를 확인하고 실행하지 않은 검증은 명시한다.
5. `git status --short`, `git diff --check`, 변경 내용을 확인한 뒤 의도한 파일만 stage하고 commit/push한다. PR에 문제와 변경, 재현 명령, 실제 검증 결과, 남은 한계를 적는다. 기본 브랜치 직접 push 대신 PR 검토를 거친다.

PR 수락 기준:

- 합의한 범위를 충족하고 다른 작업을 덮어쓰지 않는다. 신호/ROI/평가 변경은 전후 수치와 실패 이유를 함께 제시한다.
- CSV·시간·품질·provenance 계약을 지키고 합성/실제 파일 처리/정확도 평가를 구분한다. 품질 기준 변경은 근거와 영향을 설명한다.
- 분류는 피험자 분리를 유지한다. 데이터 누출 없이 Dummy 대비 결과를 확인하고 HR-only 결과를 검증된 스트레스 판단으로 표현하지 않는다.
- 검토자가 공개 가능한 입력 또는 합성 fixture로 재현할 수 있다. 실제 데이터가 필요하면 접근 조건과 로컬 준비 절차를 설명한다.

## 공개 저장소에 포함하지 않을 것

원본/가공 영상·생체 데이터, 피험자 식별자·얼굴 이미지, 개인 경로가 포함된 결과, 가상환경·캐시·실험 출력, 토큰·인증 파일·개인 설정은 올리지 않는다. `.gitignore`는 보조 장치이며 공개 가능 여부를 보증하지 않는다. PR 첨부·로그·스크린샷도 검토한다. 출처를 명시해도 재배포 권한이 생기지는 않는다. 공개 자료는 이용 조건을 확인한 집계와 합성 예제를 우선한다.
