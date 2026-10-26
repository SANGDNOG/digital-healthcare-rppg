# Digital Healthcare rPPG

일반 얼굴 영상에서 POS 맥파와 심박(HR)을 추정하고, 품질이 부족한 구간은 결과를 보류하는 디지털 헬스케어 팀 프로젝트입니다. **연구용 초기 구현이며 심리적 스트레스 점수나 의료 진단을 제공하지 않습니다.**

팀원은 [현재 상태와 남은 작업](docs/TEAM_STATUS.md)을 먼저 읽고, [협업 방법](CONTRIBUTING.md)에 따라 작업을 선택해 주세요. 담당자는 아직 확정하지 않았습니다.

## 현재 진행 상황 — 2026-10-26

| 항목 | 확인한 상태 |
| --- | --- |
| 로컬 처리 | 영상/RGB → 얼굴 ROI proxy → POS → HR/품질 → CSV·JSON·HTML·PNG 구현 |
| 테스트 | Home CPU에서 수정 후 98개 통과, 독립 재검증 98개 통과. 생체 정확도 보장이 아님 |
| 실제 영상 | UBFC-rPPG subject1 전체1547프레임 처리, 무효ROI384프레임 |
| 측정 가능 비율 | 33개 창 중2개(6.1%). 나머지31개는 샘플 부족/ROI 공백으로 보류 |
| 정확도 | 기준 신호 동기화 미확정·기준 시각 중복으로 미평가 |
| 분류 | 피험자 분리 HR-only Dummy/RF 코드 및 합성 실행 확인. 실제 조건 분류 미실시 |
| 카메라 | 명시적 capture 명령 구현·장치 모의 테스트. 실제 장치 미검증 |
| 학습 장비 | Home 설치·CPU 분석 완료. GPU 장치 인식 확인, GPU 연산은 미검증 |

**당장 다음 작업:** 얼굴 ROI 안정화, 기준 BVP와 영상 동기화 확인, 독립 샘플 평가. 낮은 유효 비율을 숨기거나 평가 샘플에 맞춰 임계값을 낮추지 않습니다.

## 최신 Home 결과와 조원 작업

- [Home 실행 결과와 해석](docs/HOME_RESULTS_2026-10-26.txt)
- [조원 할 일·10/30 중간보고서 일정](docs/TEAM_TASKS_2026-10-26.txt)
- [실제 영상의 유효 출력 집계 그래프](docs/coverage-2026-10-26.svg)

Home에서 OpenCV 4.14의 실제 AVI 프레임 읽기 비정상 종료를 확인했고, 4.11.0.86 고정 후 분석이 완료됐습니다. 기존 Mac 결과(1547프레임·무효384·유효2/33창)를 재현한 것으로, 측정 성능 향상이 아닙니다. 원본 영상·원시 생체신호·개인별 파형은 공개하지 않습니다.

## 빠른 시작

Python 3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요합니다. macOS/Linux 셸 기준이며 Windows는 WSL 사용을 권장합니다(네이티브 Windows 미검증).

```bash
git clone https://github.com/SANGDNOG/digital-healthcare-rppg.git
cd digital-healthcare-rppg
bash scripts/setup.sh
uv run --locked pytest -q
uv run --locked python -m rppg demo --output runs/my-first-demo
```

`runs/my-first-demo/report.html`을 브라우저로 열면 됩니다. demo는 **합성 신호**이며 실제 측정이 아닙니다. 출력 폴더가 이미 있으면 덮어쓰지 않으므로 새 이름을 지정하세요. setup은 uv 관리 Python과 잠금 의존성을 설치하고 데이터 폴더를 준비합니다. 데이터 다운로드·카메라 실행·학습은 자동으로 시작하지 않습니다.

```bash
uv run --locked python -m rppg --help
uv run --locked python -m rppg analyze --video /path/to/consented.mp4 --output runs/video-001
# 사용자가 직접 카메라를 사용할 때만 실행
uv run --locked python -m rppg capture --camera 0 --duration 90 --output runs/capture-001
```

`.tools/bin/uv`가 설치된 개발 환경에서는 `uv` 대신 해당 경로를 사용할 수 있습니다. 실제 카메라의 OS 권한과 실행 속도는 별도 확인해야 합니다.

## 코드와 문서

- `rppg/video.py`: 파일·카메라 입력, 타임스탬프, 단일 얼굴 Haar ROI proxy
- `rppg/signal.py`: POS, trailing20초 HR/1초 갱신, 품질 보류, 첫60초 기준선
- `rppg/evaluation.py`: timestamped HR 비교, subject-disjoint HR-only 분류
- `rppg/report.py`, `__main__.py`: CSV/JSON/HTML/PNG 및 CLI
- [사용법·입출력 규칙](docs/USAGE.md), [데이터 출처·해시·제약](docs/DATA_ACCESS.md)
- [팀 진행 현황·작업별 완료 기준](docs/TEAM_STATUS.md), [협업 안내](CONTRIBUTING.md)

`configs/baseline.json`은 구현 상수의 설명용 snapshot이며 런타임 설정 파일이 아닙니다. 임계값은 미검증 휴리스틱입니다. Haar 이마/볼 사각형은 피부 분할이나 랜드마크 추적이 아닙니다.

## 데이터와 공개 범위

원본 얼굴 영상, 기준 신호, 개인별 산출물, 가상환경, 인증정보는 저장소에 포함하지 않습니다. 데이터는 공식 출처에서 사용 조건을 확인해 별도로 받습니다. UBFC-rPPG와 스트레스 과제 데이터 UBFC-Phys는 서로 다른 자료이며, UBFC-Phys 원본은 아직 확보하지 않았습니다. 데이터 사용 동의는 코드나 데이터의 포괄적 재배포 허가를 뜻하지 않습니다.

원본·가공본은 기본 `data/raw`, `data/processed`, 결과는 `runs`에 저장합니다. 외부 데이터 경로는 setup/doctor에서 동일한 `RPPG_DATA_ROOT`를 지정합니다. 자세한 계약은 사용법 문서를 참조하세요.

이 공개본은 비공개 환경 준비 이력을 제외한 협업용 초기 스냅샷입니다. 코드의 외부 재사용 라이선스는 팀 합의 전 미지정이며, 데이터셋 이용 조건은 각 원저작자의 조건을 따릅니다.
