# Local POS MVP 사용법

저장소 루트에서 실행합니다. Python 3.11 / 기존 uv lock만 사용하며 새 의존성은 없습니다. 결과 디렉터리는 존재하면 실패합니다. 실패 후 생성된 디렉터리도 자동 삭제하지 않으므로 원인을 확인하고 새 출력 이름을 사용합니다.

```bash
uv run --locked python -m rppg --help
uv run --locked python -m rppg demo --output runs/synthetic-demo
uv run --locked python -m rppg analyze --rgb runs/synthetic-demo/rgb.csv --output runs/synthetic-rgb
uv run --locked python -m rppg analyze --video /path/to/consented.mp4 --max-seconds 120 --output runs/video-example
uv run --locked python -m rppg analyze --video /path/to/fixture.avi --roi 0,0,64,64 --fps 30 --output runs/manual-example
```

`demo`는 72 BPM 수학적 RGB 입력입니다. 실제 영상·생체신호·피험자 정확도 검증이 아닙니다. `rgb.provenance.json`에 입력 CSV SHA256과 합성 여부를 기록하며 같은 이름의 sidecar가 있으면 재분석 시 확인하고 합성 표시를 유지합니다. Sidecar가 없는 외부 CSV의 진위는 확인할 수 없습니다. JSON의 synthetic=false는 실제 데이터 검증을 뜻하지 않습니다. 보고서는 모든 경우 연구용/미검증 상태를 표시합니다.

`analyze --synthetic`은 직접 만든 영상/RGB fixture를 합성으로 표시합니다. 외부 데이터 진위는 자동 판별하지 않습니다.

`analyze`는 파일의 decoder presentation time이 유한·단조이고 명목 FPS와 대체로 일치하면 사용합니다. 그렇지 않으면 frame-index/FPS로 대체하고 메타데이터에 명시합니다. FPS가 없거나 지원 범위 밖이면 `--fps`가 필요하며 override는 항상 index/FPS를 사용합니다. 파일 최대 길이는 기본 300초, 최대 3600초입니다. 영상은 OpenCV의 번들 Haar 얼굴 검출로 정확히 얼굴 하나인 경우에만 이마·양 볼 사각형 평균 RGB를 추출합니다. 랜드마크나 피부 분할이 아니며 가림·피부색·조명·동작 성능은 미검증입니다. 얼굴 없음/여럿이면 유효하지 않은 샘플입니다. `--roi x,y,w,h`는 명시적 수동 실험용이고 프레임 밖이면 실패합니다. 자동 고정 ROI fallback은 없습니다.

사용자가 직접 실행하는 다음 명령만 카메라를 엽니다. 구현 작업에서는 실제 카메라를 열지 않았습니다.

```bash
uv run --locked python -m rppg capture --camera 0 --duration 60 --output runs/user-capture
```

카메라는 monotonic clock을 사용하고 GUI·원본 녹화 없이 RGB 평균만 저장합니다. duration 필수, 0초 초과/3600초 이하이며 길이와 샘플 상한으로 메모리를 제한합니다. 콘솔에 1초 간격 최신 HR/실패 이유를 표시합니다. 실시간 상태는 최근 구간에 한정하고 최종 보고서에서 첫 60초 baseline을 계산합니다. 장치 read 실패는 자원을 해제하며, 정상 read=false 종료는 부분 데이터 및 camera_read_failure로 기록합니다. macOS 카메라 권한·장치 실시간 동작은 사용자 실행 전 미검증입니다.

## 출력과 알고리즘

- `rgb.csv`: timestamp_s,r,g,b,roi_valid,motion_metric,brightness_metric. 시간은 초/엄격 증가, RGB·밝기는 0–255, motion은 0 이상입니다. 무효 ROI의 RGB는 공란입니다.
- `windows.csv`: 20초 trailing window/1초 hop의 HR, delta HR, baseline 상태, 품질·실패 이유. HR 공란/null은 abstention입니다.
- `report.json`, `report.html`, `waveform.png`: provenance, 입력 해시, 파라미터, valid/total 창, 마지막 유효 시간, 모든 창 실패와 0.2초 초과 간격, 최신 유효 POS 파형(상대 단위)과 HR 추이. HTML은 경로/사용자 문자열을 escape합니다. JSON NaN/Infinity는 허용하지 않습니다.

POS: Wang et al., *Algorithmic Principles of Remote PPG*, IEEE TBME 2017, DOI 10.1109/TBME.2016.2609282. 각 1.6초 구간에서 채널 평균으로 정규화하고 S1=G−B, S2=G+B−2R, h=S1+std(S1)/std(S2)×S2를 demean 및 overlap count로 정규화해 합칩니다. 0 평균/분산은 방어합니다. 현재 trailing window 내 유효한 짧은 간격만 균일 보간하며, 미래/다음 창 샘플은 사용하지 않습니다. Welch의 0.7–3Hz 최대 peak를 BPM으로 변환합니다.

품질 기준은 **미검증 임시 휴리스틱**입니다. 최소 10Hz, 유효 비율 90%, 최대 유효 샘플 간격 0.2초(창 양 끝 포함), POS std 1e-5, motion p95 0.12 이하, 밝기 10–245 및 창 내 범위 40 이하, peak ±0.1Hz 에너지 비율 0.35 이상입니다. motion은 축소 grayscale 프레임 차이와 얼굴 사각형 변위의 proxy입니다. 모든 기준은 configs/baseline.json 및 보고서에 명시됩니다. 설정 파일은 설명용 snapshot이며 CLI가 해당 파일을 동적으로 읽지는 않습니다.

Baseline은 세션 첫 60초 안의 유효 창만 사용합니다. 해당 구간에서 최소 30개가 있어야 60초 이후 고정 median HR에 대한 delta를 제공합니다. 준비 중은 collecting, 부족하면 insufficient_calibration입니다. 전체 세션 정규화나 미래 정보 사용은 없습니다. delta HR은 스트레스 점수가 아닙니다.

## Timestamped HR 평가

reference.csv는 timestamp_s,hr_bpm 필수입니다. 외부 원시 BVP를 자동 변환하거나 UBFC 영상과 정렬하지 않습니다. 동기화는 사용자가 확인해야 합니다.

```bash
uv run --locked python -m rppg evaluate --predictions runs/synthetic-demo/windows.csv --reference /path/to/reference.csv --tolerance 0.5 --output runs/hr-evaluation
```

단조 유한·중복 없는 시간, 유한 HR를 검증합니다. null HR는 평가에서 제외합니다. 명시한 tolerance 내 최근접 timestamp로만 매칭하고 시간 shift 최적화는 없습니다. 동일 reference 행은 재사용될 수 있으며 매칭 규칙을 보고합니다. 시간 overlap/유효 pair가 없으면 실패합니다. 전체/유효 prediction 수, pair 수와 coverage, MAE/RMSE, 정의될 때 correlation을 보고합니다. 예측 보고서의 합성 provenance를 이어받습니다. 자체 합성 reference 실험은 `--synthetic`을 추가합니다.

## 조건부 baseline 분류

```bash
uv run --locked python -m rppg classify --features /path/to/features.csv --output runs/hr-classification
```

입력은 subject_id,label,hr_bpm만 허용하며 다른 열은 실패합니다. task/scenario/BVP/EDA/식별자를 모델 feature로 넣지 않습니다. delta는 calibration provenance를 입증할 수 없어 이 버전에서 허용하지 않습니다. 최소 3명과 2개 클래스가 필요하며 모든 train fold에 전체 클래스가 있어야 합니다. 최소 3명은 안정적인 성능 평가를 보장하지 않습니다. blank HR는 train fold median imputation, scaler도 train에서만 fit합니다. 30–220 범위 밖/비유한 HR는 제외 이유를 보고합니다. blank subject/label도 제외합니다.

GroupKFold(min(5, 피험자 수))에서 subject를 완전히 분리해 DummyClassifier와 seed=42, 100 trees, max_depth=5 RandomForest를 비교합니다. pooled out-of-fold balanced accuracy/macro F1/confusion matrix/각 클래스 recall, fold별 피험자 목록을 저장하며 hyperparameter search는 없습니다. demo는 자동 분류하지 않습니다. 사용자 제공 label의 진위를 확인하지 않으며 실제 labeled 데이터 없이 학습/성능 성공을 주장하지 않습니다. fixture 분류 명령에는 `--synthetic`을 추가하세요.

## 검증

```bash
uv run --locked pytest -q
uv run --locked python scripts/doctor.py
```

합성 주파수·조명, flat/invalid/gap/motion/brightness abstention, 저 FPS·짧은 구간, 잘못된 시간, no-face/manual fixture video, 장치 예외 시 release, 알려진 reference 오차, subject 분리/금지 열, CLI 합성 provenance/overwrite를 검증합니다. 실제 생체 정확도, 광범위 피부색/동작/조명 성능, 카메라 실시간 작동은 검증하지 않았습니다. 실제 데이터 출처/접근 현황은 docs/DATA_ACCESS.md를 참조합니다.
