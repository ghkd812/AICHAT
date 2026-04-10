# 🤖 내 AI 챗봇 (Hazel)

사내 IT 담당자를 위한 개인용 AI 어시스턴트입니다.
OpenAI API 기반으로 구축되었으며 Streamlit으로 웹 UI를 제공합니다.

---

## 주요 기능

### 대화 관리
- 대화 세션 생성 / 삭제 / 목록 조회
- 첫 메시지로 대화 제목 자동 생성
- 사용자별 대화 기록 분리 저장

### 인증
- 아이디/비밀번호 로그인 (SHA-256 해시 저장)
- `users.json` 기반 계정 관리
- 로그인 상태 세션 유지 및 로그아웃

### AI 모델 선택
| 모델 | 특징 |
|------|------|
| `gpt-4o-mini` | 빠르고 저렴한 범용 모델 |
| `gpt-4.1-mini` | 균형잡힌 성능 (기본값) |
| `gpt-4.1` | 고성능 범용 모델 |
| `o4-mini` / `o3` | 복잡한 추론이 필요한 작업용 (추론 모델) |

- 답변 길이 조절: 짧게 / 보통 / 자세히
- 스트리밍 응답 (실시간 타이핑 효과)

### 파일 첨부 및 분석
지원 파일 형식:

| 유형 | 확장자 |
|------|--------|
| 문서 | PDF, DOCX, TXT |
| 스프레드시트 | XLSX, XLS, CSV |
| 프레젠테이션 | PPTX |
| 이미지 | PNG, JPG, JPEG, WebP |

- Excel / CSV 파일 미리보기 (시트별)
- 이미지 파일 미리보기

### 이미지 분석 (Vision)
- 이미지를 직접 AI에 전달하여 판독
- 여권, 비자, 신분증, 계약서, 문서 캡처 분석 특화
- 주요 추출 정보: 이름, 여권번호, 국적, 생년월일, 발급일, 만료일, 비자 종류, 체류기간

### 구조화 결과 자동 처리
- AI 답변에서 JSON 블록 또는 마크다운 표 자동 감지
- DataFrame으로 변환 후 테이블 표시
- Excel 파일로 즉시 다운로드 가능

### 코드 블록 처리
- 답변 내 코드 블록 자동 추출 및 하이라이팅
- 코드 파일 저장 다운로드 버튼 제공

### 검색 기능
- **네이버 검색 API**: 로컬 정보 검색, 이미지 검색
- **OpenAI 웹 검색**: 최신 정보 실시간 검색

### 이미지 생성
- DALL-E 기반 이미지 생성 기능

### MongoDB 연동
- MongoDB Atlas를 통한 대화 기록 영구 저장
- **RAG (Retrieval-Augmented Generation)**: MongoDB Atlas Vector Search 기반 문서 Q&A

### 기타
- 토큰 사용량 및 비용 표시
- 대화 내용 검색 기능
- 모바일 대응 UI (사이드바 토글)

---

## 기술 스택

| 항목 | 내용 |
|------|------|
| UI 프레임워크 | Streamlit |
| AI API | OpenAI (GPT-4.1, o4-mini, o3, DALL-E) |
| 검색 | Naver Search API, OpenAI Web Search |
| DB | MongoDB Atlas (Vector Search 포함) |
| 인증 | SHA-256 해시 / users.json |
| 주요 라이브러리 | pandas, pypdf, python-pptx, python-docx, pymongo |

---

## 설치 및 실행

### 1. 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정
```bash
OPENAI_API_KEY=sk-...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
MONGODB_URI=mongodb+srv://...
```

### 3. 계정 등록
`users.json` 파일에 사용자 추가:
```json
[
  {
    "username": "admin",
    "password_hash": "<SHA-256 해시값>"
  }
]
```

### 4. 실행
```bash
streamlit run app.py
```

---

## 주의사항
- 사내 전용 프라이빗 서비스입니다.
- `users.json`은 절대 공개 저장소에 커밋하지 마세요.
- API 키는 반드시 환경변수 또는 Streamlit secrets로 관리하세요.
