import os
import io
import json
import re
import base64
from datetime import datetime

import pandas as pd
import streamlit as st
from docx import Document
from openai import OpenAI
from pypdf import PdfReader
from pptx import Presentation

# ---------------------------------
# 기본 설정
# ---------------------------------
st.set_page_config(
    page_title="내 AI 챗봇",
    page_icon="🤖",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
}
section[data-testid="stSidebar"] {
    width: 320px !important;
}
.chat-title {
    font-size: 2.2rem;
    font-weight: 800;
    margin-bottom: 1rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="chat-title">🤖 내 AI 챗봇</div>', unsafe_allow_html=True)

# ---------------------------------
# 경로 / 상수
# ---------------------------------
BASE_CHAT_DIR = "chats"
os.makedirs(BASE_CHAT_DIR, exist_ok=True)

# ---------------------------------
# OpenAI
# ---------------------------------
api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")

if not api_key:
    st.error("OPENAI_API_KEY가 없습니다. 환경변수 또는 Streamlit secrets에 설정하세요.")
    st.stop()

client = OpenAI(api_key=api_key)

# ---------------------------------
# 로그인 관련
# ---------------------------------
def load_users():
    try:
        users = st.secrets.get("USERS", [])
        if not isinstance(users, list):
            return []
        return users
    except Exception as e:
        st.error(f"Secrets 읽기 오류: {e}")
        return []

def verify_login(username: str, password: str) -> bool:
    users = load_users()
    username = str(username).strip()

    for user in users:
        if (
            str(user.get("username", "")).strip() == username
            and str(user.get("password", "")) == password
        ):
            return True
    return False

def get_user_chat_dir():
    username = st.session_state.get("username", "guest")
    user_dir = os.path.join(BASE_CHAT_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

# ---------------------------------
# 파일 읽기 함수
# ---------------------------------
def read_pdf(file):
    try:
        file.seek(0)
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        return f"[PDF 읽기 실패: {e}]"

def read_excel(file):
    try:
        file.seek(0)
        excel = pd.ExcelFile(file)
        text_parts = []
        previews = []

        for sheet_name in excel.sheet_names:
            df = pd.read_excel(excel, sheet_name=sheet_name)
            previews.append((sheet_name, df.head(20)))
            text_parts.append(f"[시트: {sheet_name}]")
            text_parts.append(df.head(50).to_string(index=False))

        return "\n\n".join(text_parts), previews
    except Exception as e:
        return f"[Excel 읽기 실패: {e}]", []

def read_csv(file):
    try:
        file.seek(0)
        df = pd.read_csv(file)
        return df.head(50).to_string(index=False), df.head(20)
    except Exception:
        try:
            file.seek(0)
            df = pd.read_csv(file, encoding="cp949")
            return df.head(50).to_string(index=False), df.head(20)
        except Exception as e:
            return f"[CSV 읽기 실패: {e}]", None

def read_ppt(file):
    try:
        file.seek(0)
        prs = Presentation(file)
        text = ""
        for i, slide in enumerate(prs.slides, start=1):
            slide_texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    value = shape.text.strip()
                    if value:
                        slide_texts.append(value)
            text += f"\n[슬라이드 {i}]\n" + "\n".join(slide_texts) + "\n"
        return text.strip()
    except Exception as e:
        return f"[PPT 읽기 실패: {e}]"

def read_docx(file):
    try:
        file.seek(0)
        doc = Document(file)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        return f"[DOCX 읽기 실패: {e}]"

def read_txt(file):
    file.seek(0)
    raw = file.getvalue()
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")

def image_to_base64(file):
    file.seek(0)
    return base64.b64encode(file.getvalue()).decode()

# ---------------------------------
# 엑셀 변환 / 구조화 데이터 추출
# ---------------------------------
def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name="result"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def extract_json_block(text: str):
    if not text:
        return None

    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```[\w]*\s*(\[\s*{.*?}\s*\])\s*```",
        r"```[\w]*\s*(\{\s*.*?\s*\})\s*```",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                pass

    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    return None

def json_to_dataframe(data):
    if isinstance(data, list):
        if len(data) == 0:
            return pd.DataFrame()
        if all(isinstance(x, dict) for x in data):
            return pd.DataFrame(data)
        return pd.DataFrame({"value": data})

    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                return pd.DataFrame(value)
        return pd.DataFrame([data])

    return None

def parse_markdown_table_to_df(text: str):
    if not text or "|" not in text:
        return None

    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) < 2:
        return None

    header_idx = None
    for i in range(len(lines) - 1):
        if re.fullmatch(r"\|?[\s:-|]+\|?", lines[i + 1]):
            header_idx = i
            break

    if header_idx is None:
        return None

    header_line = lines[header_idx]
    data_lines = lines[header_idx + 2:]

    headers = [h.strip() for h in header_line.strip("|").split("|")]
    rows = []

    for line in data_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(cells)

    if not rows:
        return None

    return pd.DataFrame(rows, columns=headers)

def try_build_result_dataframe(full_text: str):
    data = extract_json_block(full_text)
    if data is not None:
        df = json_to_dataframe(data)
        if df is not None and not df.empty:
            return df

    df = parse_markdown_table_to_df(full_text)
    if df is not None and not df.empty:
        return df

    return None

# ---------------------------------
# 대화 저장 함수
# ---------------------------------
def chat_path(chat_id: str) -> str:
    return os.path.join(get_user_chat_dir(), f"{chat_id}.json")

def create_new_chat():
    chat_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    data = {
        "title": "새 대화",
        "messages": [
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
        ]
    }
    with open(chat_path(chat_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return chat_id

def load_chat(chat_id: str):
    path = chat_path(chat_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "title": "새 대화",
        "messages": [
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
        ]
    }

def save_chat(chat_id: str, data: dict):
    with open(chat_path(chat_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def list_chats():
    files = []
    user_dir = get_user_chat_dir()

    if not os.path.exists(user_dir):
        return []

    for name in os.listdir(user_dir):
        if name.endswith(".json"):
            files.append(name.replace(".json", ""))
    files.sort(reverse=True)

    result = []
    for chat_id in files:
        try:
            data = load_chat(chat_id)
            result.append({
                "id": chat_id,
                "title": data.get("title", "제목 없음")
            })
        except Exception:
            pass
    return result

def delete_chat(chat_id: str):
    path = chat_path(chat_id)
    if os.path.exists(path):
        os.remove(path)

def make_title_from_messages(messages):
    for msg in messages:
        if msg["role"] == "user":
            text = msg["content"].strip().replace("\n", " ")
            return text[:20] if len(text) > 20 else text
    return "새 대화"

# ---------------------------------
# 프롬프트
# ---------------------------------
def build_system_prompt(answer_length: str) -> str:
    if answer_length == "짧게":
        length_rule = "답변은 핵심만 2~3문장으로 간단히 설명한다."
    elif answer_length == "보통":
        length_rule = "답변은 3~6문장 정도로 설명한다."
    else:
        length_rule = "답변은 충분히 자세하게 설명하고, 필요하면 예시와 항목 정리를 포함한다."

    return f"""
너는 친절하고 유능한 한국어 AI 챗봇이다.
항상 한국어로 답변한다.
모르는 내용은 추측하지 말고 불확실하다고 말한다.
사용자가 파일을 첨부한 경우 첨부 내용을 우선 참고한다.
사용자가 이미지(여권, 비자, 신분증, 계약서, 문서 캡처 등)를 첨부하면 OCR 텍스트에 의존하지 말고 이미지 자체를 직접 판독해서 답변한다.

이미지에서 특히 아래 정보가 있으면 정리한다.
- 이름
- 여권번호
- 국적
- 생년월일
- 발급일
- 만료일
- 비자 종류
- 체류기간

생년월일, 발급일, 만료일은 가능하면 YYYY-MM-DD 형태로 정리한다.
확실하지 않은 값은 추정이라고 표시하거나 비워둘 수 있다.
이미지 속 텍스트가 흐리거나 일부 가려져 있으면 보이는 범위 내에서만 답변한다.
사용자가 표, 엑셀, 리스트, 정리본을 요청하면 가능하면 JSON 배열 또는 표 형태로 구조화해서 제공한다.
가능하면 표 형태나 JSON 형태로 정리한다.
{length_rule}
"""

# ---------------------------------
# 세션 초기화
# ---------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = None

if "uploaded_files_cache" not in st.session_state:
    st.session_state.uploaded_files_cache = []

if "answer_length" not in st.session_state:
    st.session_state.answer_length = "보통"

if "model_name" not in st.session_state:
    st.session_state.model_name = "gpt-4.1-mini"

if "last_result_df" not in st.session_state:
    st.session_state.last_result_df = None

# ---------------------------------
# 로그인 화면
# ---------------------------------
if not st.session_state.logged_in:
    st.subheader("🔐 로그인")

    login_username = st.text_input("아이디")
    login_password = st.text_input("비밀번호", type="password")

    if st.button("로그인", use_container_width=True):
        if verify_login(login_username, login_password):
            st.session_state.logged_in = True
            st.session_state.username = login_username
            st.success("로그인되었습니다.")
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

    st.info("Streamlit Secrets에 USERS 계정을 등록해두면 됩니다.")
    st.stop()

# ---------------------------------
# 로그인 후 현재 대화 초기화
# ---------------------------------
if "current_chat_id" not in st.session_state:
    chats = list_chats()
    if chats:
        st.session_state.current_chat_id = chats[0]["id"]
    else:
        st.session_state.current_chat_id = create_new_chat()

# ---------------------------------
# 사이드바
# ---------------------------------
with st.sidebar:
    st.write(f"로그인 사용자: **{st.session_state.username}**")

    if st.button("로그아웃", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.uploaded_files_cache = []
        st.session_state.last_result_df = None
        if "current_chat_id" in st.session_state:
            del st.session_state["current_chat_id"]
        st.rerun()

    st.divider()
    st.header("대화")

    if st.button("＋ 새 대화", use_container_width=True):
        st.session_state.current_chat_id = create_new_chat()
        st.session_state.uploaded_files_cache = []
        st.session_state.last_result_df = None
        st.rerun()

    st.divider()

    for chat in list_chats():
        col1, col2 = st.columns([4, 1])

        with col1:
            if st.button(chat["title"], key=f"open_{chat['id']}", use_container_width=True):
                st.session_state.current_chat_id = chat["id"]
                st.session_state.uploaded_files_cache = []
                st.session_state.last_result_df = None
                st.rerun()

        with col2:
            if st.button("🗑", key=f"del_{chat['id']}", use_container_width=True):
                deleting_current = (st.session_state.current_chat_id == chat["id"])
                delete_chat(chat["id"])
                remaining = list_chats()
                if deleting_current:
                    if remaining:
                        st.session_state.current_chat_id = remaining[0]["id"]
                    else:
                        st.session_state.current_chat_id = create_new_chat()
                st.rerun()

    st.divider()
    st.header("답변 설정")

    model_options = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"]
    if st.session_state.model_name not in model_options:
        st.session_state.model_name = "gpt-4.1-mini"

    st.session_state.model_name = st.selectbox(
        "모델",
        model_options,
        index=model_options.index(st.session_state.model_name)
    )

    length_options = ["짧게", "보통", "자세히"]
    if st.session_state.answer_length not in length_options:
        st.session_state.answer_length = "보통"

    st.session_state.answer_length = st.selectbox(
        "답변 길이",
        length_options,
        index=length_options.index(st.session_state.answer_length)
    )

# ---------------------------------
# 현재 대화 로드
# ---------------------------------
current_data = load_chat(st.session_state.current_chat_id)
messages = current_data["messages"]

# ---------------------------------
# 파일 업로드
# ---------------------------------
st.subheader("📎 파일 첨부")

uploaded_files = st.file_uploader(
    "여기에 파일을 드래그하거나 클릭해서 선택하세요",
    type=[
        "pdf", "xlsx", "xls", "csv",
        "pptx", "docx", "txt",
        "png", "jpg", "jpeg", "webp"
    ],
    accept_multiple_files=True,
    key="main_file_uploader"
)

if uploaded_files is not None and len(uploaded_files) > 0:
    st.session_state.uploaded_files_cache = uploaded_files

active_files = st.session_state.uploaded_files_cache

file_context = ""
image_inputs = []

if active_files:
    st.success(f"{len(active_files)}개 파일 업로드됨")

    for f in active_files:
        ext = f.name.split(".")[-1].lower()
        st.write("첨부됨:", f.name)

        try:
            if ext == "pdf":
                text = read_pdf(f)
                file_context += f"\n\n[PDF: {f.name}]\n{text}"

            elif ext in ["xlsx", "xls"]:
                excel_text, previews = read_excel(f)
                file_context += f"\n\n[EXCEL: {f.name}]\n{excel_text}"
                for sheet_name, df in previews:
                    with st.expander(f"미리보기: {f.name} / {sheet_name}", expanded=False):
                        st.dataframe(df, use_container_width=True)

            elif ext == "csv":
                csv_text, preview_df = read_csv(f)
                file_context += f"\n\n[CSV: {f.name}]\n{csv_text}"
                if preview_df is not None:
                    with st.expander(f"미리보기: {f.name}", expanded=False):
                        st.dataframe(preview_df, use_container_width=True)

            elif ext == "pptx":
                text = read_ppt(f)
                file_context += f"\n\n[PPTX: {f.name}]\n{text}"

            elif ext == "docx":
                text = read_docx(f)
                file_context += f"\n\n[DOCX: {f.name}]\n{text}"

            elif ext == "txt":
                text = read_txt(f)
                file_context += f"\n\n[TXT: {f.name}]\n{text}"

            elif ext in ["png", "jpg", "jpeg", "webp"]:
                with st.expander(f"이미지 미리보기: {f.name}", expanded=False):
                    st.image(f, caption=f"{f.name} 원본", use_container_width=True)

                file_context += f"""
[이미지 파일: {f.name}]
이 이미지는 사용자가 첨부한 원본 이미지입니다.
OCR 전처리 텍스트는 제공하지 않으니, 필요한 경우 이미지 자체를 직접 분석하세요.
여권, 비자, 신분증, 문서 이미지, 캡처 화면일 수 있으므로
이름, 여권번호, 국적, 생년월일, 발급일, 만료일, 비자 종류, 체류기간 등의 정보가 보이면 정리하세요.
"""

                image_inputs.append({
                    "type": "input_image",
                    "image_url": f"data:{f.type};base64,{image_to_base64(f)}"
                })

        except Exception as e:
            st.error(f"{f.name} 처리 중 오류: {e}")

    if st.button("첨부 파일 비우기"):
        st.session_state.uploaded_files_cache = []
        st.rerun()
else:
    st.info("업로드된 파일 없음")

with st.expander("첨부 데이터 확인", expanded=False):
    st.write("file_context 길이:", len(file_context))
    st.write("image_inputs 개수:", len(image_inputs))

# ---------------------------------
# 대화 출력
# ---------------------------------
for msg in messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ---------------------------------
# 사용자 입력
# ---------------------------------
user_input = st.chat_input("메시지를 입력하세요")

if user_input:
    messages.append({"role": "user", "content": user_input})

    if current_data.get("title") in ["새 대화", "제목 없음"]:
        current_data["title"] = make_title_from_messages(messages)

    current_data["messages"] = messages
    save_chat(st.session_state.current_chat_id, current_data)

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""

        try:
            history_for_model = []
            for msg in messages[:-1]:
                history_for_model.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            user_content = [
                {
                    "type": "input_text",
                    "text": f"""사용자 질문:
{user_input}

첨부 파일 내용:
{file_context if file_context else "첨부된 파일 없음"}
"""
                }
            ]

            if image_inputs:
                user_content.extend(image_inputs)

            stream = client.responses.create(
                model=st.session_state.model_name,
                input=[
                    {"role": "system", "content": build_system_prompt(st.session_state.answer_length)},
                    *history_for_model,
                    {"role": "user", "content": user_content}
                ],
                stream=True
            )

            for event in stream:
                if event.type == "response.output_text.delta":
                    full_text += event.delta
                    placeholder.markdown(full_text + "▌")
                elif event.type == "response.completed":
                    break

            placeholder.markdown(full_text)

        except Exception as e:
            full_text = f"오류가 발생했습니다: {e}"
            placeholder.error(full_text)

        messages.append({"role": "assistant", "content": full_text})
        current_data["messages"] = messages
        save_chat(st.session_state.current_chat_id, current_data)

        result_df = try_build_result_dataframe(full_text)
        st.session_state.last_result_df = result_df

        if result_df is not None and not result_df.empty:
            st.subheader("📊 AI 결과 표")
            st.dataframe(result_df, use_container_width=True)

            result_excel = dataframe_to_excel_bytes(result_df, sheet_name="ai_result")
            st.download_button(
                label="📥 AI 결과 Excel 다운로드",
                data=result_excel,
                file_name="ai_result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"download_ai_excel_{st.session_state.current_chat_id}"
            )
